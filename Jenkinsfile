pipeline {
  agent any
  environment {
    VENV = '.venv'
    SONARQUBE = 'SonarQube'
    PYTHON = 'python3'
  }
  stages {
    stage('Checkout'){ steps{ checkout scm } }
    stage('Setup Python'){
      steps{
        sh 'python3 -m venv ${VENV}'
        sh '. ${VENV}/bin/activate && pip install --upgrade pip'
        sh '. ${VENV}/bin/activate && pip install -r requirements.txt pytest pytest-cov coverage sonar-scanner-cli'
      }
    }
    stage('Start DB'){
      steps{ sh 'docker compose up -d db && sleep 10' }
    }
    stage('DB migrate (test)'){
      steps{
        sh '''
          . ${VENV}/bin/activate
          export SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://zfm:zfm@localhost:${DB_PORT:-5432}/zfm_test
          docker exec $(docker ps -qf name=_db_) psql -U zfm -c "CREATE DATABASE zfm_test;" || true
          flask db upgrade || flask init-db
        '''
      }
    }
    stage('Tests'){
      steps{
        sh '''
          . ${VENV}/bin/activate
          export SQLALCHEMY_DATABASE_URI=postgresql+psycopg2://zfm:zfm@localhost:${DB_PORT:-5432}/zfm_test
          pytest -q --maxfail=1 --disable-warnings --cov=oraculoicms_app --cov-report=xml:coverage.xml --junitxml=report-junit.xml
        '''
      }
      post {
        always { junit 'report-junit.xml' }
      }
    }
    stage('Sonar'){
      steps{
        withSonarQubeEnv('SonarQube'){
          sh '. ${VENV}/bin/activate && sonar-scanner -Dsonar.login=$SONAR_AUTH_TOKEN || true'
        }
      }
    }
    stage('Quality Gate'){
    when { branch 'main' } // só valida na main
      steps{
        timeout(time: 10, unit: 'MINUTES'){ waitForQualityGate abortPipeline: true }
      }
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
      emailext subject: '✅ zfm-calculator: Build ${BUILD_NUMBER} OK',
               body: "Pipeline finalizada com sucesso.",
               to: "${EMAIL_TO}"
    }
    failure {
      emailext subject: '❌ zfm-calculator: Build ${BUILD_NUMBER} falhou',
               body: "Verifique o console do Jenkins.",
               to: "${EMAIL_TO}"
    }
  }
}
