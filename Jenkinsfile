pipeline {
    agent any
    
    stages {
        stage('1. Checkout Code') {
            steps {
                git branch: 'main', url: 'https://github.com/VOTRE_PSEUDO/VOTRE_REPO.git'
            }
        }
        
        stage('2. Build Django Docker Image') {
            steps {
                script {
                    sh 'docker build -t workforce-django-app:latest .'
                }
            }
        }
        
        stage('3. Security Scan (Trivy)') {
            steps {
                // Scan de l'image Docker fraîchement construite
                sh 'trivy image --severity HIGH,CRITICAL workforce-django-app:latest'
            }
        }
        
        stage('4. Verification') {
            steps {
                echo "Build et Scan de l'application Django réussis avec succès !"
            }
        }
    }
}