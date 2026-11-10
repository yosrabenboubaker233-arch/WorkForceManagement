pipeline {
    agent any

    environment {
        DOCKER_IMAGE = 'yosra158/workforce-django-app'
        CREDENTIALS_ID = 'docker-hub-credentials'
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
                    // Connexion à Docker Hub de manière sécurisée
                    withCredentials([usernamePassword(credentialsId: "${CREDENTIALS_ID}", usernameVariable: 'DOCKER_USER', passwordVariable: 'DOCKER_PASS')]) {
                        sh 'echo "$DOCKER_PASS" | docker login -u "$DOCKER_USER" --password-stdin'
                    }

                    // Build de l'image Docker
                    sh "docker build -t ${DOCKER_IMAGE}:latest ."
                    
                    // Optionnel : Pousser l'image sur Docker Hub
                    sh "docker push ${DOCKER_IMAGE}:latest"
                }
            }
        }

        stage('3. Security Scan (Trivy)') {
            steps {
                echo "Exécution du scan de sécurité..."
                // sh "trivy image ${DOCKER_IMAGE}:latest"
            }
        }
    }
}
