pipeline {
    agent any

    environment {
        DOCKER_IMAGE = 'yosra158/workforce-django-app'
        CREDENTIALS_ID = '6679e6e3-015a-4495-83ce-9326fa796750'
    }

    stages {
        stage('1. Checkout SCM') {
            steps {
                checkout scm
            }
        }

        stage('2. Build Django Docker Image') {
            steps {
                script {
                    withCredentials([usernamePassword(credentialsId: "${CREDENTIALS_ID}", usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                        sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                    }

                    sh "docker build -t ${DOCKER_IMAGE}:latest ."
                    sh "docker push ${DOCKER_IMAGE}:latest"
                }
            }
        }
    }
}
