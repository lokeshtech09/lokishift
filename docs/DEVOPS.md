# LokiShift on AWS — Jenkins + SonarQube + Docker + ECR + EC2

Every `git push` to `main` runs this pipeline:

```
GitHub ──webhook──▶ Jenkins ──▶ Test & Lint ──▶ SonarQube ──▶ Quality Gate ──▶ docker build ──▶ Amazon ECR ──▶ EC2 (app)
                                 (parallel)      (analysis)    (pass/fail)                        (registry)      (deploy + health check)
```

| File | What it does |
|---|---|
| `Jenkinsfile` | The pipeline (pipeline-as-code) |
| `sonar-project.properties` | What SonarQube scans, where coverage is |
| `Dockerfile` | Multi-stage image: Next.js build → Python 3.13 runtime, non-root user, health check |
| `deploy/deploy.sh` | Runs on the app server: pull from ECR, swap container, health check, roll back on failure |
| `deploy/setup-jenkins-server.sh` | One-time install of Jenkins + Docker + AWS CLI + SonarQube |
| `deploy/setup-app-server.sh` | One-time install of Docker + AWS CLI on the app server |
| `.githooks/pre-push` | Same tests on your laptop before a push ("shift left") |

---

## Setup (about 60–90 minutes the first time)

### 1. AWS: two EC2 instances + one IAM role each

| | CI server | App server |
|---|---|---|
| Name | `lokishift-ci` | `lokishift-app` |
| AMI | Ubuntu 24.04 | Ubuntu 24.04 |
| Type | **t3.large** (SonarQube needs ~4 GB RAM) | t3.small |
| Disk | 30 GB | 15 GB |
| IAM role | `AmazonEC2ContainerRegistryPowerUser` | `AmazonEC2ContainerRegistryReadOnly` |

Put both in the **same VPC/subnet** so Jenkins can SSH to the app server by private IP.

**Security groups** (inbound):

| Port | CI server | App server |
|---|---|---|
| 22 (SSH) | My IP | My IP **and** the CI server's security group |
| 8080 (Jenkins) | My IP, plus [GitHub webhook IPs](https://api.github.com/meta) (or 0.0.0.0/0 for the demo) | — |
| 9000 (SonarQube) | My IP | — |
| 3000 (LokiShift) | — | **My IP / classroom IP only** |

> ⚠️ LokiShift has no login, and the Settings page holds an AI API key that anyone who can
> open the app can spend. Keep port 3000 limited to your own IP (or the classroom's), and stop
> the instances after the demo.

### 2. Install the software

```bash
# CI server
scp -i key.pem deploy/setup-jenkins-server.sh ubuntu@<ci-public-ip>:
ssh -i key.pem ubuntu@<ci-public-ip> 'sudo bash setup-jenkins-server.sh'

# App server
scp -i key.pem deploy/setup-app-server.sh ubuntu@<app-public-ip>:
ssh -i key.pem ubuntu@<app-public-ip> 'sudo bash setup-app-server.sh'
```

### 3. SonarQube (http://&lt;ci-public-ip&gt;:9000)

1. Log in `admin` / `admin`, set a new password.
2. **My Account → Security → Generate token** (type: Global Analysis) → copy it.
3. **Administration → Configuration → Webhooks → Create**
   URL: `http://<ci-PRIVATE-ip>:8080/sonarqube-webhook/` — this is what lets the Quality Gate stage finish.

### 4. Jenkins (http://&lt;ci-public-ip&gt;:8080)

1. Unlock with the initial password, **Install suggested plugins**, create your admin user.
2. **Manage Jenkins → Plugins → Available**: install **Docker Pipeline**, **SonarQube Scanner**, **SSH Agent**.
3. **Manage Jenkins → Credentials → Global → Add**
   - *Secret text*, id `sonar-token`, value = the SonarQube token
   - *SSH Username with private key*, id `app-server-ssh`, username `ubuntu`, key = your `key.pem` contents
4. **Manage Jenkins → System → SonarQube servers**: tick *Environment variables*, add
   name `sonarqube`, URL `http://<ci-PRIVATE-ip>:9000`, token `sonar-token`.
5. **Manage Jenkins → Tools → SonarQube Scanner installations**: add, name `sonar-scanner`, tick *Install automatically*.
6. **New Item → `lokishift` → Pipeline**
   - *Build Triggers*: tick **GitHub hook trigger for GITScm polling**
   - *Pipeline*: **Pipeline script from SCM** → Git → `https://github.com/lokeshtech09/lokishift.git`, branch `*/main`, script path `Jenkinsfile`

### 5. Edit the four values at the top of `Jenkinsfile`

```groovy
AWS_REGION  = 'us-east-2'   // your AWS project's Region
AWS_ACCOUNT = '123456789012'    // aws sts get-caller-identity
APP_HOST    = '10.0.1.20'       // app server PRIVATE ip
APP_USER    = 'ubuntu'
```

Commit and push.

### 6. GitHub webhook

Repo → **Settings → Webhooks → Add webhook**
Payload URL `http://<ci-public-ip>:8080/github-webhook/`, content type `application/json`, *Just the push event*.

### 7. First run

Click **Build Now** once (the first build registers the webhook trigger). After that, every push builds by itself.
Open `http://<app-public-ip>:3000` → Settings → add an AI connection → you're live.

---

## When something goes red

| Stage | Usual cause | Fix |
|---|---|---|
| Backend tests | `docker: permission denied` | `sudo usermod -aG docker jenkins && sudo systemctl restart jenkins` |
| SonarQube analysis | `Not authorized` / can't connect | Check token, and use the **private** IP in the server URL |
| Quality Gate | Hangs until timeout | SonarQube webhook missing or wrong URL (step 3.3) |
| Quality Gate | `FAILED` | Working as intended: open the SonarQube project to see which condition failed |
| SonarQube container keeps stopping | `max virtual memory areas too low` | `sudo sysctl -w vm.max_map_count=524288` |
| Push to ECR | `AccessDenied` | CI instance has no IAM role, or the wrong policy |
| Deploy | `Permission denied (publickey)` | Wrong key in `app-server-ssh`, or port 22 not open from the CI security group |
| Deploy | Health check fails | `docker logs lokishift` on the app server; the script already rolled back |

## Cost

t3.large + t3.small ≈ US$0.10/hour together (us-east-2, on-demand). **Stop both instances after the demo**; data and settings survive a stop.
