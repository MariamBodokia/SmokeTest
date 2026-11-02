pipeline {
    agent {
        docker {
            image 'mcr.microsoft.com/playwright/python:v1.49.1-noble'
            args '-u root'
        }
    }
    parameters {
        string(name: 'BASE_URL', defaultValue: 'http://host.docker.internal:8000', description: 'Application URL')
    }
    stages {
        stage('Install test dependencies') {
            steps {
                sh 'pip install -r smoke-tests/requirements.txt'
            }
        }
        stage('Smoke tests') {
            steps {
                retry(3) {
                    sh 'mkdir -p artifacts && BASE_URL="$BASE_URL" pytest smoke-tests --junitxml=artifacts/junit.xml --tracing=retain-on-failure --screenshot=only-on-failure'
                }
            }
            post {
                always {
                    junit allowEmptyResults: true, testResults: 'artifacts/junit.xml'
                    archiveArtifacts allowEmptyArchive: true, artifacts: 'artifacts/**,test-results/**'
                }
            }
        }
    }
}
