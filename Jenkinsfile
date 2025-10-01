pipeline {
  agent any
  environment {
    IMAGE = "oraculoicms_app:${env.BUILD_NUMBER}"
    TEST_DB = "postgresql+psycopg2://postgres:postgres@db:5432/oraculoicms_test"
  }

  stages {
    stage('Checkout') { steps { checkout scm } }

    stage('Build image') {
      steps { sh 'docker build -t ${IMAGE} .' }
    }

    stage('Start test DB') {
      steps {
        sh '''
          # Sobe só o Postgres do compose (ou use docker run)
          docker compose up -d db
          # Espera o DB responder
          for i in {1..30}; do
            docker compose exec -T db pg_isready -U postgres && break
            sleep 2
          done
          # Cria o banco de teste
          docker compose exec -T db psql -U postgres -c "CREATE DATABASE oraculoicms_test;" || true
        '''
      }
    }

    stage('DB migrate (test)') {
      steps {
        sh '''
          # roda migração dentro da imagem da app, conectando no serviço "db" da mesma network do compose
          docker run --rm --network $(basename "$PWD")_default \
            -e SQLALCHEMY_DATABASE_URI=${TEST_DB} \
            ${IMAGE} sh -lc "flask db upgrade || flask init-db"
        '''
      }
    }

    stage('Tests') {
      steps {
        sh '''
          docker run --rm --network $(basename "$PWD")_default \
            -e SQLALCHEMY_DATABASE_URI=${TEST_DB} \
            -v $PWD:/workspace -w /workspace \
            ${IMAGE} sh -lc "pytest -q --maxfail=1 --disable-warnings \
              --cov=oraculoicms_app --cov-report=xml:coverage.xml \
              --junitxml=report-junit.xml"
        '''
      }
      post {
        always {
          junit 'report-junit.xml'
          publishCoverage adapters: [coberturaAdapter('coverage.xml')]
        }
      }
    }

    stage('Sonar') {
      steps {
        withSonarQubeEnv('SonarQube') {
          sh '''
            docker run --rm -v $PWD:/usr/src \
              sonarsource/sonar-scanner-cli \
              -Dsonar.projectBaseDir=/usr/src \
              -Dsonar.login=$SONAR_AUTH_TOKEN || true
          '''
        }
      }
    }

    stage('Quality Gate') {
      when { branch 'main' }
      steps { timeout(time: 10, unit: 'MINUTES') { waitForQualityGate abortPipeline: true } }
    }

    stage('Deploy') {
      when { anyOf { branch 'staging'; branch 'develop'; branch 'main' } }
      steps {
        script {
          if (env.BRANCH_NAME == 'main') {
            sh 'docker compose -f docker-compose.prod.yml up -d'
          } else {
            sh 'docker compose -f docker-compose.staging.yml up -d'
          }
        }
      }
    }
  }

  post {
    success {
      emailext subject: "✅ oraculoicms_app: Build ${BUILD_NUMBER} OK",
               body: "Pipeline finalizada com sucesso.",
               to: "${EMAIL_TO}"
    }
    failure {
      emailext subject: "❌ oraculoicms_app: Build ${BUILD_NUMBER} falhou",
               body: "Verifique o console do Jenkins.",
               to: "${EMAIL_TO}"
    }
  }
}
