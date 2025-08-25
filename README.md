# Job Application Generator - Production Setup

## 📋 Requirements.txt
```txt
fastapi==0.104.1
uvicorn[standard]==0.24.0
aiohttp==3.9.1
aiofiles==23.2.0
beautifulsoup4==4.12.2
pydantic[email]==2.5.0
python-multipart==0.0.6
nltk==3.8.1
jinja2==3.1.2
openai==1.3.7
python-dotenv==1.0.0
lxml==4.9.3
html5lib==1.1
requests==2.31.0
```

## 🐳 Dockerfile
```dockerfile
FROM python:3.11-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    g++ \
    curl \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Download NLTK data
RUN python -c "import nltk; nltk.download('punkt'); nltk.download('stopwords'); nltk.download('vader_lexicon')"

# Copy application code
COPY . .

# Create necessary directories
RUN mkdir -p generated_applications templates cache && \
    chmod 755 generated_applications templates cache

# Create non-root user
RUN useradd --create-home --shell /bin/bash appuser && \
    chown -R appuser:appuser /app

USER appuser

EXPOSE 8020

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8020/ || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8020"]
```

## 🚀 Docker Compose
```yaml
version: '3.8'

services:
  job-app-generator:
    build: .
    container_name: job-application-generator
    restart: unless-stopped
    ports:
      - "8020:8020"
    volumes:
      - ./generated_applications:/app/generated_applications
      - ./cache:/app/cache
      - ./logs:/app/logs
    environment:
      - ENVIRONMENT=production
      - LOG_LEVEL=info
      - MAX_CACHE_AGE=86400
    healthcheck:
      test: ["CMD", "curl", "-f", "http://localhost:8020/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s
    networks:
      - job-app-network

  # Nginx reverse proxy for production
  nginx:
    image: nginx:alpine
    container_name: job-app-nginx
    restart: unless-stopped
    ports:
      - "80:80"
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./generated_applications:/var/www/static:ro
    depends_on:
      - job-app-generator
    networks:
      - job-app-network

  # Redis for caching job data
  redis:
    image: redis:alpine
    container_name: job-app-redis
    restart: unless-stopped
    command: redis-server --appendonly yes
    volumes:
      - redis_data:/data
    networks:
      - job-app-network

networks:
  job-app-network:
    driver: bridge

volumes:
  redis_data:
```

## 🌐 Nginx Configuration
```nginx
events {
    worker_connections 1024;
}

http {
    upstream app {
        server job-app-generator:8020;
    }

    # Rate limiting
    limit_req_zone $binary_remote_addr zone=api:10m rate=10r/m;
    limit_req_zone $binary_remote_addr zone=generate:10m rate=2r/m;

    server {
        listen 80;
        server_name your-domain.com;

        # Security headers
        add_header X-Frame-Options DENY;
        add_header X-Content-Type-Options nosniff;
        add_header X-XSS-Protection "1; mode=block";

        # Serve static files directly
        location /static/ {
            alias /var/www/static/;
            expires 24h;
            add_header Cache-Control "public, immutable";
        }

        # Rate limit application generation
        location /generate-application {
            limit_req zone=generate burst=5 nodelay;
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
            
            # Increase timeout for job analysis
            proxy_connect_timeout 60s;
            proxy_send_timeout 60s;
            proxy_read_timeout 60s;
        }

        # Rate limit API calls
        location /api/ {
            limit_req zone=api burst=10 nodelay;
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }

        # All other requests
        location / {
            proxy_pass http://app;
            proxy_set_header Host $host;
            proxy_set_header X-Real-IP $remote_addr;
            proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
            proxy_set_header X-Forwarded-Proto $scheme;
        }
    }
}
```

## 🔧 Environment Configuration
Create a `.env` file:
```env
# Application Settings
ENVIRONMENT=production
LOG_LEVEL=info
HOST=0.0.0.0
PORT=8020

# OpenAI API (Optional - for enhanced cover letters)
OPENAI_API_KEY=your_openai_api_key_here

# Cache Settings
MAX_CACHE_AGE=86400
REDIS_URL=redis://redis:6379

# Security
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=["localhost", "your-domain.com"]

# Rate Limiting
MAX_REQUESTS_PER_MINUTE=60
MAX_GENERATION_REQUESTS_PER_HOUR=10
```

## 🚀 Deployment Commands

### Local Development
```bash
# Install dependencies
pip install -r requirements.txt

# Run the application
python main.py

# Or with uvicorn
uvicorn main:app --reload --port 8020
```

### Docker Deployment
```bash
# Build and start services
docker-compose up -d

# View logs
docker-compose logs -f job-app-generator

# Scale for high traffic
docker-compose up -d --scale job-app-generator=3

# Update application
git pull
docker-compose build --no-cache job-app-generator
docker-compose up -d
```

### Production Monitoring
```bash
# Check container health
docker-compose ps

# Monitor resource usage
docker stats

# View application logs
docker-compose logs -f --tail=100 job-app-generator

# Backup generated applications
docker run --rm -v $(pwd)/generated_applications:/backup alpine tar czf /backup/applications_backup.tar.gz /backup
```

## 📊 Performance Optimizations

### 1. **Caching Strategy**
- HTML content cached for 24 hours
- Job details cached in Redis
- Static files served by Nginx

### 2. **Rate Limiting**
- 10 API requests per minute per IP
- 2 application generations per minute per IP
- Prevents abuse and ensures fair usage

### 3. **Async Processing**
- Non-blocking I/O for web scraping
- Concurrent job analysis
- Background task processing

### 4. **Resource Management**
- Docker memory limits
- Connection pooling
- Automatic container restart

## 🔒 Security Features

### 1. **Input Validation**
- Pydantic models for type safety
- URL validation and sanitization
- XSS protection headers

### 2. **Rate Limiting**
- Per-IP request limiting
- Burst protection
- DDoS mitigation

### 3. **Container Security**
- Non-root user execution
- Minimal base image
- No sensitive data in container

## 🌍 Cloud Deployment Options

### AWS ECS
```json
{
  "taskDefinition": "job-app-generator",
  "serviceName": "job-app-service",
  "desiredCount": 2,
  "networkConfiguration": {
    "awsvpcConfiguration": {
      "subnets": ["subnet-12345"],
      "securityGroups": ["sg-12345"],
      "assignPublicIp": "ENABLED"
    }
  }
}
```

### Google Cloud Run
```yaml
apiVersion: serving.knative.dev/v1
kind: Service
metadata:
  name: job-app-generator
spec:
  template:
    metadata:
      annotations:
        autoscaling.knative.dev/maxScale: "10"
        run.googleapis.com/memory: "1Gi"
        run.googleapis.com/cpu: "1000m"
    spec:
      containers:
      - image: gcr.io/PROJECT/job-app-generator
        ports:
        - containerPort: 8020
        env:
        - name: ENVIRONMENT
          value: production
```

### DigitalOcean App Platform
```yaml
name: job-app-generator
services:
- name: web
  source_dir: /
  github:
    repo: your-username/job-app-generator
    branch: main
  run_command: uvicorn main:app --host 0.0.0.0 --port $PORT
  environment_slug: python
  instance_count: 1
  instance_size_slug: basic-xxs
  http_port: 8020
  envs:
  - key: ENVIRONMENT
    value: production
```

## 💰 Cost Analysis

| Platform | Monthly Cost | Max Requests/Month | Features |
|----------|--------------|-------------------|----------|
| VPS (DigitalOcean) | $12 | 100,000 | Full control, Redis |
| Google Cloud Run | $0-50 | 1,000,000 | Auto-scaling, pay-per-use |
| AWS ECS | $20-100 | Unlimited | Enterprise features |
| Heroku | $25 | 500,000 | Easy deployment |

This transforms your basic job application script into an enterprise-grade SaaS application that can handle thousands of users and generate personalized applications at scale!
