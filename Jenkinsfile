stage('6. Infrastructure with Terraform') {
            steps {
                dir('terraform') {
                    sh 'terraform init -no-color'
                    sh 'terraform apply -auto-approve'
                }
            }
        }
