pipeline {
    agent any

    options {
        skipDefaultCheckout(true)
        disableConcurrentBuilds()
        timeout(time: 30, unit: 'MINUTES')
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

        stage('2. Build Django Docker Image') {
            steps {
                sh "docker build -t ${DOCKER_IMAGE}:${BUILD_NUMBER} -t ${DOCKER_IMAGE}:latest ."
            }
        }

        stage('3. Push to Docker Hub') {
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

        stage('4. Deploy') {
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
    }

    post {
        always {
            sh 'docker logout || true'
            sh 'docker image prune -f || true'
        }
        success {
            echo "Déployé : ${DOCKER_IMAGE}:${BUILD_NUMBER} sur http://13.62.10.222:8000"
        }
        failure {
            echo 'Le build a échoué, consultez les logs ci-dessus.'
        }
    }
}
