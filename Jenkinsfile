pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 45, unit: 'MINUTES')
    }

    parameters {
        choice(name: 'DEPLOY_TARGET', choices: ['docker', 'kubernetes'],
               description: 'Cible de déploiement')
    }

    environment {
        DOCKER_IMAGE   = 'yosra158/workforce-django-app'
        CREDENTIALS_ID = '3b6e329f-f8e0-4ffb-a45c-cc949cf8e6b0'
    }

    stages {
        stage('1. Checkout SCM') {
            steps {
                checkout scm
            }
        }

        stage('2. SonarQube Analysis') {
            steps {
                script {
                    def scannerHome = tool 'SonarQubeScanner'
                    withSonarQubeEnv('MonSonarQube') {
                        sh """
                            ${scannerHome}/bin/sonar-scanner \
                              -Dsonar.projectKey=workforce-django \
                              -Dsonar.sources=WorkForce \
                              -Dsonar.exclusions=**/migrations/**,**/static/**
                        """
                    }
                }
            }
        }

        stage('3. Build Django Docker Image') {
            steps {
                sh "docker build -f Dockerfile -t ${DOCKER_IMAGE}:${BUILD_NUMBER} -t ${DOCKER_IMAGE}:latest ."
            }
        }

        stage('4. Trivy Scan') {
            steps {
                sh '''
                    docker run --rm \
                      -v /var/run/docker.sock:/var/run/docker.sock \
                      -v trivy_cache:/root/.cache/ \
                      aquasec/trivy:latest image \
                      --severity HIGH,CRITICAL --exit-code 0 --no-progress \
                      ${DOCKER_IMAGE}:${BUILD_NUMBER}
                '''
            }
        }

        stage('5. Push to Docker Hub') {
            steps {
                withCredentials([usernamePassword(credentialsId: "${CREDENTIALS_ID}",
                                                  usernameVariable: 'DOCKER_USER',
                                                  passwordVariable: 'DOCKER_PASS')]) {
                    sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                    sh "docker push ${DOCKER_IMAGE}:${BUILD_NUMBER}"
                    sh "docker push ${DOCKER_IMAGE}:latest"
                }
            }
        }

        stage('6. Deploy Docker') {
            when { expression { (params.DEPLOY_TARGET ?: 'docker') == 'docker' } }
            steps {
                sh '''
                    docker rm -f workforce-app || true
                    docker run -d --name workforce-app --restart unless-stopped \
                      -p 8000:8000 \
                      -v workforce_data:/app/data \
                      ${DOCKER_IMAGE}:${BUILD_NUMBER}
                '''
            }
        }

        stage('7. Deploy Kubernetes') {
            when { expression { params.DEPLOY_TARGET == 'kubernetes' } }
            steps {
                sh '''
                    kubectl apply -f kubernetes/
                    kubectl set image deployment/workforce-django-deployment \
                      workforce-django=${DOCKER_IMAGE}:${BUILD_NUMBER}
                    kubectl rollout status deployment/workforce-django-deployment --timeout=180s \
                      || { kubectl rollout undo deployment/workforce-django-deployment; exit 1; }
                '''
            }
        }

        stage('8. Monitoring Stack') {
            steps {
                dir('monitoring') {
                    sh 'docker compose up -d'
                }
            }
        }
    }

    post {
        always {
            sh 'docker logout || true'
            sh 'docker image prune -f || true'
        }
        success {
            echo "Déployé : ${DOCKER_IMAGE}:${BUILD_NUMBER}"
        }
        failure {
            echo 'Le build a échoué, consultez les logs ci-dessus.'
        }
    }
}
