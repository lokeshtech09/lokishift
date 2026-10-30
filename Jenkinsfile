// LokiShift CI/CD pipeline
//
//   GitHub push ─▶ Jenkins ─▶ tests ─▶ SonarQube ─▶ Quality Gate ─▶ Docker image ─▶ Amazon ECR ─▶ EC2
//
// Jenkins needs (see docs/DEVOPS.md):
//   plugins     : Pipeline, Git, GitHub, Timestamper, Docker Pipeline, SonarQube Scanner, SSH Agent, JUnit
//   tools       : SonarQube Scanner installation named  "sonar-scanner"
//   server      : SonarQube server named                "sonarqube"
//   credentials : SSH key for the app server, id        "app-server-ssh"
//   on the host : docker + aws CLI, and an EC2 IAM role allowed to push to ECR

pipeline {
    agent any

    environment {
        // ── Change these four for your AWS account ─────────────────────────────
        AWS_REGION   = 'us-east-2'   // your AWS project's Region
        AWS_ACCOUNT  = '319793009477'
        APP_HOST     = '18.216.54.193'            // the EC2 instance's PRIVATE IP (same server as Jenkins)
        APP_USER     = 'ubuntu'
        // ───────────────────────────────────────────────────────────────────────
        ECR_REPO     = 'lokishift'
        REGISTRY     = "${AWS_ACCOUNT}.dkr.ecr.${AWS_REGION}.amazonaws.com"
        IMAGE        = "${REGISTRY}/${ECR_REPO}"
    }

    options {
        timestamps()
        timeout(time: 40, unit: 'MINUTES')
        buildDiscarder(logRotator(numToKeepStr: '15'))
        disableConcurrentBuilds()
    }

    triggers {
        // Jenkins checks GitHub for new commits every minute (no inbound port needed).
        pollSCM('* * * * *')
        // Also fires instantly if you add a GitHub webhook to http://<jenkins>:8080/github-webhook/
        githubPush()
    }

    stages {
        stage('Checkout') {
            steps {
                checkout scm
                script {
                    // Every image is traceable to its build and commit, e.g. 42-8956133
                    def sha = sh(returnStdout: true, script: 'git rev-parse --short HEAD').trim()
                    env.IMAGE_TAG = "${env.BUILD_NUMBER}-${sha}"
                }
                sh 'git log -1 --pretty="%h %an: %s"'
            }
        }

        stage('Test & Lint') {
            parallel {
                stage('Backend tests') {
                    agent {
                        docker {
                            image 'ghcr.io/astral-sh/uv:python3.13-bookworm'
                            reuseNode true
                        }
                    }
                    environment {
                        UV_CACHE_DIR = "${WORKSPACE}/.cache/uv"
                    }
                    steps {
                        dir('apps/backend') {
                            sh 'uv sync --extra dev --frozen'
                            // The LLM is stubbed: no API key and no network calls in tests.
                            sh '''
                                uv run --with pytest-cov pytest -q -p no:cacheprovider \
                                    --cov=app --cov-report=xml:coverage.xml \
                                    --junitxml=reports/pytest.xml
                            '''
                        }
                    }
                    post {
                        always { junit allowEmptyResults: true, testResults: 'apps/backend/reports/pytest.xml' }
                    }
                }

                stage('Frontend typecheck & lint') {
                    agent {
                        docker {
                            image 'node:22-bookworm'
                            reuseNode true
                        }
                    }
                    environment {
                        npm_config_cache = "${WORKSPACE}/.cache/npm"
                        NEXT_TELEMETRY_DISABLED = '1'
                    }
                    steps {
                        dir('apps/frontend') {
                            sh 'npm ci --no-audit --no-fund'
                            sh 'npm run typecheck'
                            sh 'npm run lint'
                        }
                    }
                }
            }
        }

        stage('SonarQube analysis') {
            steps {
                script {
                    def scannerHome = tool 'sonar-scanner'
                    withSonarQubeEnv('sonarqube') {
                        sh "${scannerHome}/bin/sonar-scanner -Dsonar.projectVersion=${env.IMAGE_TAG}"
                    }
                }
            }
        }

        stage('Quality Gate') {
            steps {
                // SonarQube calls back through its webhook; a red gate stops the release here.
                timeout(time: 10, unit: 'MINUTES') {
                    waitForQualityGate abortPipeline: true
                }
            }
        }

        stage('Docker build') {
            steps {
                sh "docker build -t ${IMAGE}:${env.IMAGE_TAG} -t ${IMAGE}:latest ."
            }
        }

        stage('Push to Amazon ECR') {
            steps {
                // Uses the Jenkins EC2 instance's IAM role: no AWS keys stored in Jenkins.
                sh '''
                    aws ecr describe-repositories --repository-names "$ECR_REPO" --region "$AWS_REGION" >/dev/null 2>&1 \
                      || aws ecr create-repository --repository-name "$ECR_REPO" --region "$AWS_REGION"
                    aws ecr get-login-password --region "$AWS_REGION" \
                      | docker login --username AWS --password-stdin "$REGISTRY"
                    docker push "$IMAGE:$IMAGE_TAG"
                    docker push "$IMAGE:latest"
                '''
            }
        }

        stage('Deploy to EC2') {
            // Only the main branch goes live (works for both single-branch and multibranch jobs).
            when { expression { (env.BRANCH_NAME ?: env.GIT_BRANCH ?: 'main').endsWith('main') } }
            steps {
                sshagent(credentials: ['app-server-ssh']) {
                    sh '''
                        scp -o StrictHostKeyChecking=accept-new deploy/deploy.sh "$APP_USER@$APP_HOST:/tmp/deploy.sh"
                        ssh -o StrictHostKeyChecking=accept-new "$APP_USER@$APP_HOST" \
                            "bash /tmp/deploy.sh '$REGISTRY' '$IMAGE:$IMAGE_TAG' '$AWS_REGION'"
                    '''
                }
            }
        }
    }

    post {
        always {
            // Keep the Jenkins disk from filling up with old images.
            sh 'docker image prune -f || true'
        }
        success {
            echo "✅ LokiShift ${env.IMAGE_TAG} is live on http://${APP_HOST}:3000"
        }
        failure {
            echo '❌ Pipeline failed: nothing was deployed. Check the red stage above.'
        }
    }
}
