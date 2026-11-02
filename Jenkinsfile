pipeline {
    agent {
        docker {
            image 'mcr.microsoft.com/playwright/python:v1.49.1-noble'
            args '-u root'
        }
    }
    parameters {
        string(name: 'BASE_URL', defaultValue: 'http://host.docker.internal:8000', description: 'Application URL')
        string(name: 'SMOKEMONITOR_URL', defaultValue: 'http://host.docker.internal:8080', description: 'SmokeMonitor URL')
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
                    withEnv(["SMOKEMONITOR_STATUS=${currentBuild.currentResult}"]) {
                        sh '''
                      python - <<'PY'
                      import json, os, urllib.request
                      payload = {
                          "job": os.environ.get("JOB_NAME", "local-smoke"),
                          "build": os.environ.get("BUILD_NUMBER", "local"),
                          "status": os.environ.get("SMOKEMONITOR_STATUS", "FAILURE"),
                          "attempt": 1,
                          "base_url": os.environ["BASE_URL"],
                          "failed_tests": []
                      }
                      request = urllib.request.Request(
                          os.environ["SMOKEMONITOR_URL"] + "/api/results",
                          data=json.dumps(payload).encode(),
                          headers={"Content-Type": "application/json", "X-SmokeMonitor-Token": os.environ.get("SMOKEMONITOR_TOKEN", "local-monitor-token")},
                          method="POST")
                      try:
                          urllib.request.urlopen(request, timeout=10)
                      except Exception as error:
                          print("SmokeMonitor publication failed:", error)
                      PY
                        '''
                    }
                }
            }
        }
    }
}
