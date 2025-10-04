pipeline {
  agent any
   parameters {
		booleanParam(name: 'RUN_BUILD_IMAGE_DOCKER',   defaultValue: true,  description: 'Executa build de imagem no docker')
		booleanParam(name: 'RUN_PYLINT',   defaultValue: true,  description: 'Executa analise pylint https://pylint.readthedocs.io/en/stable/')
		booleanParam(name: 'RUN_BANDIT',   defaultValue: true,  description: 'Executa analise bandit https://bandit.readthedocs.io/en/latest/')
		booleanParam(name: 'RUN_TESTS_UNIT',   defaultValue: true,  description: 'Executa testes unitários ')
		booleanParam(name: 'RUN_SONAR',   defaultValue: true,  description: 'Envia análise ao SonarQube http://10.0.0.200:9001/dashboard?id=oraculoicms')
		booleanParam(name: 'DEPLOY_STG',  defaultValue: true,  description: 'Faz deploy em STAGING')
		booleanParam(name: 'DEPLOY_PRD',  defaultValue: false, description: 'Faz deploy em PRODUÇÃO')
  }
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
		when { expression { params.RUN_BUILD_IMAGE_DOCKER } }
		steps {
		sh '''
		  DOCKER_BUILDKIT=1 docker build \
		  	--build-arg BUILDKIT_INLINE_CACHE=1 \
			--build-arg BUILD_REV=${BUILD_NUMBER} \
			--build-arg APP_HASH=$(git rev-parse --short HEAD) \
			-t ${IMAGE} -f Dockerfile .
		'''
	  }
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


	stage('Gerando Relatório de Análise Pylint') {
	  when { expression { params.RUN_PYLINT } }
	  steps {
		sh '''
		  docker run --rm \
			--network ${COMPOSE_PROJECT_NAME}_default \
			-e FLASK_APP=oraculoicms_app.wsgi \
			-e DISABLE_SHEETS=1 \
			-e DISABLE_SCHEDULER=1 \
			-v $PWD:/workspace -w /workspace \
			${IMAGE} sh -lc "pylint oraculoicms_app -f parseable -r n --output=pylint-report.txt || true"
		'''
	  }
	}


	stage('Gerando Relatório de Análise Bandit') {
	  when { expression { params.RUN_BANDIT } }
	  steps {
		sh '''
		  docker run --rm \
			--network ${COMPOSE_PROJECT_NAME}_default \
			-e FLASK_APP=oraculoicms_app.wsgi \
			-e DISABLE_SHEETS=1 \
			-e DISABLE_SCHEDULER=1 \
			-v $PWD:/workspace -w /workspace \
			${IMAGE} sh -lc "bandit -r oraculoicms_app -f json -o bandit-report.json || true"
		'''
	  }
	}


	stage('Unit tests') {
	  when { expression { params.RUN_TESTS_UNIT } }
	  steps {
		sh '''
		  docker run --rm \
			--network ${COMPOSE_PROJECT_NAME}_default \
			-e FLASK_APP=oraculoicms_app.wsgi:create_app \
			-e DISABLE_SHEETS=1 \
			-e DISABLE_SCHEDULER=1 \
			-v $PWD:/workspace -w /workspace \
			${IMAGE} sh -lc '
			  set -e
			  coverage erase
			  coverage run -m pytest -q --maxfail=1 --disable-warnings
			  # gera XML respeitando o .coveragerc (relative_files + paths)
			  coverage xml -o coverage-reports/coverage.xml
			'
		'''
	  }
	  post {
		always {
		  junit 'coverage-reports/pytest-report.xml'
		  publishCoverage(
			adapters: [coberturaAdapter('coverage-reports/coverage.xml')],
			sourceFileResolver: sourceFiles('STORE_LAST_BUILD')
		  )
		}
	  }
	}


    stage('Deploy STAGING (banco 2) — não bloqueia por QG') {
	  when { expression { params.DEPLOY_STG } }
      steps {
        sh '''
          # usa .env.staging (oraculoicms_staging)
          docker compose -f ${COMPOSE_BASE} -f ${COMPOSE_STG} up -d --force-recreate --no-deps web-staging
        '''
      }
    }

    stage('SonarQube Analysis') {
	  when { expression { params.RUN_SONAR } }
      steps {
		  withSonarQubeEnv('SonarQube MG'){
			  sh '''
				  /opt/sonar-scanner/bin/sonar-scanner \
				  -Dsonar.projectKey=oraculoicms \
				  -Dsonar.sources=oraculoicms_app,xml_parser \
				  -Dsonar.tests=tests \
				  -Dsonar.exclusions=**/migrations/**,**/__pycache__/**,**/templates/**,**/static/** \
				  -Dsonar.python.version=3.12 \
				  -Dsonar.python.coverage.reportPaths=coverage-reports/coverage.xml \
				  -Dsonar.python.xunit.reportPath=coverage-reports/pytest-report.xml \
				  -Dsonar.python.pylint.reportPaths=pylint-report.txt \
				  -Dsonar.python.bandit.reportPaths=bandit-report.json \
				  -Dsonar.verbose=true
			  '''
				// Adjust based on your project structure
        }
      }
    }

    stage('Quality Gate (obrigatório pra Produção)') {
	  when { expression { params.RUN_DEPLOY_PRD } }
      steps {
        timeout(time: 10, unit: 'MINUTES') { waitForQualityGate abortPipeline: true }
      }
    }

    stage('Deploy PRODUÇÃO (banco 3)') {
	  when { expression { params.RUN_DEPLOY_PRD } }
      steps {
        sh '''
          # usa .env.production (oraculoicms)
          docker compose -f ${COMPOSE_BASE} -f ${COMPOSE_PRD} up -d
        '''
      }
    }
  }
}
