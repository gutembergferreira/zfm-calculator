pipeline {
  agent any
  environment {
    IMAGE        = "oraculoicms:${env.BUILD_NUMBER}"
    COMPOSE_BASE = "docker-compose.yml"
    COMPOSE_STG  = "docker-compose.staging.yml"
    COMPOSE_PRD  = "docker-compose.prod.yml"
    TEST_DB_URL  = "postgresql+psycopg://postgres:postgres@db:5432/oraculoicms_test"
    COMPOSE_PROJECT_NAME= "oraculoicms"

  }

  stages {
    stage('Checkout'){ steps{ checkout scm } }

    stage('Build image') {
      steps { sh 'docker build -t ${IMAGE} -f Dockerfile .' }
    }

	stage('Start DB (tests)') {
	  steps {
		sh '''
		  set -e

		  # Sobe só o serviço de DB do compose base
		  docker compose -f ${COMPOSE_BASE} up -d db

		  echo "Aguardando Postgres ficar pronto..."
		  # Loop robusto: testa pg_isready até OK (timeout ~120s)
		  for i in $(seq 1 60); do
			if docker compose -f ${COMPOSE_BASE} exec -T db pg_isready -U postgres -d postgres >/dev/null 2>&1; then
			  echo "Postgres OK (pg_isready)."
			  break
			fi
			echo "Postgres ainda não respondeu... tentativa ${i}/60"
			sleep 2
		  done

		  # Falha se ainda não respondeu
		  docker compose -f ${COMPOSE_BASE} exec -T db pg_isready -U postgres -d postgres

		  echo "Criando database de testes (oraculoicms_test), se não existir..."
		  docker compose -f ${COMPOSE_BASE} exec -T db psql -U postgres -d postgres -tc "SELECT 1 FROM pg_database WHERE datname='oraculoicms_test'" | grep -q 1 \
			|| docker compose -f ${COMPOSE_BASE} exec -T db psql -U postgres -d postgres -c "CREATE DATABASE oraculoicms_test;"
			'''
		  }
		}

	stage('Migrate (tests)') {
	  steps {
		sh """
		  docker run --rm \
			--network ${COMPOSE_PROJECT_NAME}_default \
			-e FLASK_APP=oraculoicms_app.wsgi \
			-e FLASK_ENV=testing \
			-e DISABLE_SHEETS=1 \
			-e DISABLE_SCHEDULER=1 \
			-e SQLALCHEMY_DATABASE_URI=${TEST_DB_URL} \
			-e DATABASE_URL=${TEST_DB_URL} \
			-w /app \
			${IMAGE} sh -lc 'set -e
			  echo "[migrate] FLASK_ENV=\$FLASK_ENV"
			  echo "[migrate] SQLALCHEMY_DATABASE_URI=\$SQLALCHEMY_DATABASE_URI"
			  if [ ! -d migrations ]; then
				echo "[migrate] migrations/ não existe — executando flask db init"
				flask db init
			  fi
			  if ! flask db upgrade; then
				echo "[migrate] Sem revisões — gerando migração inicial"
				flask db migrate -m "init"
				flask db upgrade || flask init-db
			  fi
			'
		"""
	  }
	}

	stage('Unit tests') {
	  steps {
		sh '''
		  docker run --rm \
			--network ${COMPOSE_PROJECT_NAME}_default \
			-e FLASK_APP=oraculoicms_app.wsgi \
			-e DISABLE_SHEETS=1 \
       		-e DISABLE_SCHEDULER=1 \
			-v $PWD:/workspace -w /workspace \
			${IMAGE} sh -lc "pytest -q --maxfail=1 --disable-warnings \
			  --cov=oraculoicms_app --cov-report=xml:coverage.xml \
			  --junitxml=report-junit.xml"
		'''
	  }
	post {
	  always {
		junit 'report-junit.xml'
		publishCoverage(
		  adapters: [coberturaAdapter('coverage.xml')],
		  sourceFileResolver: sourceFiles('STORE_LAST_BUILD')
		)
	  }
	}
	}

    stage('Deploy STAGING (banco 2) — não bloqueia por QG') {
      steps {
        sh '''
          # usa .env.staging (oraculoicms_staging)
          docker compose -f ${COMPOSE_BASE} -f ${COMPOSE_STG} up -d
        '''
      }
    }

    stage('SonarQube Analysis') {
      steps {
		  withSonarQubeEnv('SonarQube MG'){
			  sh '''
				  /opt/sonar-scanner/bin/sonar-scanner \
				  -Dsonar.projectKey=oraculoicms \
				  -Dsonar.language=py \
				  -Dsonar.sources=. \
				  -Dsonar.tests=tests \
				  -Dsonar.exclusions=**/tests/**,**/migrations/**,**/__pycache__/** \
				  -Dsonar.python.version=3.12 \
				  -Dsonar.python.coverage.reportPath=coverage.xml \
				  -Dsonar.verbose=true
			  '''
				// Adjust based on your project structure -Dsonar.python.xunit.reportPath=report-junit.xml
        }
      }
    }

    stage('Quality Gate (obrigatório pra Produção)') {
      steps {
        timeout(time: 10, unit: 'MINUTES') { waitForQualityGate abortPipeline: true }
      }
    }

    stage('Deploy PRODUÇÃO (banco 3)') {
      steps {
        sh '''
          # usa .env.production (oraculoicms)
          docker compose -f ${COMPOSE_BASE} -f ${COMPOSE_PRD} up -d
        '''
      }
    }
  }
}
