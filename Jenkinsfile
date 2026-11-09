pipeline {
    agent any
    
    stages {
        stage('2. Build Django Docker Image') {
            steps {
                script {
                    sh 'docker build -t workforce-django-app:latest .'
                }
            }
        }
        
        stage('3. Security Scan (Trivy)') {
            steps {
                // Scan de l'image Docker fraîchement construite contre les vulnérabilités
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
