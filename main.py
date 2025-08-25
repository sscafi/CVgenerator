from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
from fastapi.responses import HTMLResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, EmailStr, HttpUrl, validator
import asyncio
import aiohttp
import aiofiles
from bs4 import BeautifulSoup
import re
import nltk
from typing import List, Optional, Dict, Any
import logging
from pathlib import Path
import json
from datetime import datetime
import uuid
from contextlib import asynccontextmanager
import os
from jinja2 import Template
import openai  # For AI enhancement (optional)

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
OUTPUT_DIR = Path("generated_applications")
TEMPLATES_DIR = Path("templates")
CACHE_DIR = Path("cache")

# Ensure directories exist
for directory in [OUTPUT_DIR, TEMPLATES_DIR, CACHE_DIR]:
    directory.mkdir(exist_ok=True)

# Download NLTK data
try:
    nltk.download('punkt', quiet=True)
    nltk.download('stopwords', quiet=True)
    nltk.download('vader_lexicon', quiet=True)
except:
    logger.warning("Failed to download NLTK data")

class UserProfile(BaseModel):
    """User profile data model"""
    name: str
    email: EmailStr
    phone: str
    experience_years: int
    degree: str
    skills: List[str]
    previous_roles: List[str] = []
    achievements: List[str] = []
    linkedin_url: Optional[str] = None
    portfolio_url: Optional[str] = None
    
    @validator('experience_years')
    def validate_experience(cls, v):
        if v < 0 or v > 50:
            raise ValueError('Experience years must be between 0 and 50')
        return v

class JobApplicationRequest(BaseModel):
    """Job application request model"""
    job_url: HttpUrl
    user_profile: UserProfile
    cover_letter_style: str = "professional"  # professional, creative, technical
    include_salary_expectation: bool = False
    custom_message: Optional[str] = None

class JobDetails(BaseModel):
    """Extracted job details model"""
    company_name: str
    job_title: str
    job_description: str
    requirements: List[str]
    salary_range: Optional[str] = None
    location: Optional[str] = None
    job_type: Optional[str] = None  # full-time, part-time, contract
    industry: Optional[str] = None

class ApplicationResponse(BaseModel):
    """Application generation response model"""
    success: bool
    application_id: str
    company_name: str
    job_title: str
    cover_letter_path: Optional[str] = None
    cv_path: Optional[str] = None
    message: str

class WebScraper:
    """Enhanced web scraping with multiple strategies"""
    
    def __init__(self):
        self.session = None
        self.headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        }
    
    async def __aenter__(self):
        self.session = aiohttp.ClientSession(headers=self.headers)
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self.session:
            await self.session.close()
    
    async def fetch_html(self, url: str) -> Optional[str]:
        """Fetch HTML content with retry logic and caching"""
        cache_file = CACHE_DIR / f"{hash(url)}.html"
        
        # Check cache first (24 hour expiry)
        if cache_file.exists():
            file_age = datetime.now().timestamp() - cache_file.stat().st_mtime
            if file_age < 86400:  # 24 hours
                async with aiofiles.open(cache_file, 'r', encoding='utf-8') as f:
                    return await f.read()
        
        try:
            async with self.session.get(str(url), timeout=30) as response:
                if response.status == 200:
                    html_content = await response.text()
                    # Cache the result
                    async with aiofiles.open(cache_file, 'w', encoding='utf-8') as f:
                        await f.write(html_content)
                    return html_content
                else:
                    logger.error(f"HTTP {response.status} for URL: {url}")
                    return None
        except Exception as e:
            logger.error(f"Error fetching URL {url}: {e}")
            return None
    
    def extract_job_details(self, html_content: str, url: str) -> JobDetails:
        """Extract comprehensive job details from HTML"""
        soup = BeautifulSoup(html_content, 'html.parser')
        
        # Remove script and style elements
        for element in soup(["script", "style"]):
            element.decompose()
        
        # Extract job title
        job_title = self._extract_job_title(soup)
        
        # Extract company name
        company_name = self._extract_company_name(soup, job_title)
        
        # Extract job description
        job_description = self._extract_job_description(soup)
        
        # Extract requirements
        requirements = self._extract_requirements(soup, job_description)
        
        # Extract additional details
        salary_range = self._extract_salary(soup, job_description)
        location = self._extract_location(soup)
        job_type = self._extract_job_type(soup, job_description)
        industry = self._extract_industry(soup, company_name)
        
        return JobDetails(
            company_name=company_name,
            job_title=job_title,
            job_description=job_description,
            requirements=requirements,
            salary_range=salary_range,
            location=location,
            job_type=job_type,
            industry=industry
        )
    
    def _extract_job_title(self, soup: BeautifulSoup) -> str:
        """Extract job title with multiple strategies"""
        selectors = [
            'h1[data-automation="job-detail-title"]',  # SEEK
            'h1.jobsearch-JobInfoHeader-title',        # Indeed
            '.job-title h1',
            '.job-header h1',
            'h1',
            '[data-testid="job-title"]'
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.get_text(strip=True):
                return element.get_text(strip=True)
        
        # Fallback to title tag
        title_tag = soup.find('title')
        if title_tag:
            title_text = title_tag.get_text(strip=True)
            # Clean up common patterns in job titles
            title_text = re.sub(r'\s*[-|]\s*(Jobs?|Careers?|Hiring).*$', '', title_text, flags=re.IGNORECASE)
            return title_text
        
        return "Unknown Position"
    
    def _extract_company_name(self, soup: BeautifulSoup, job_title: str) -> str:
        """Extract company name with improved accuracy"""
        # Try common selectors first
        selectors = [
            '[data-automation="advertiser-name"]',     # SEEK
            '.company-name',
            '.employer-name',
            '[data-testid="company-name"]',
            '.company a'
        ]
        
        for selector in selectors:
            element = soup.select_one(selector)
            if element and element.get_text(strip=True):
                return element.get_text(strip=True)
        
        # Extract from text using regex
        text_content = soup.get_text()
        company_patterns = [
            r'(?:Company|Employer|Organization):\s*([A-Z][a-zA-Z\s&\'\.]+)',
            r'(?:at|@)\s+([A-Z][a-zA-Z\s&\'\.]+?)(?:\s|$)',
            r'([A-Z][a-zA-Z\s&\'\.]{2,30})\s+(?:is hiring|seeks|looking for)'
        ]
        
        for pattern in company_patterns:
            match = re.search(pattern, text_content)
            if match:
                company = match.group(1).strip()
                # Filter out common false positives
                if len(company) > 2 and company not in ['Apply Now', 'Click Here', 'More Info']:
                    return company
        
        return "Company Name Not Found"
    
    def _extract_job_description(self, soup: BeautifulSoup) -> str:
        """Extract comprehensive job description"""
        description_selectors = [
            '[data-automation="jobAdDetails"]',
            '.job-description',
            '.jobsearch-jobDescriptionText',
            '.job-details',
            '.description'
        ]
        
        for selector in description_selectors:
            element = soup.select_one(selector)
            if element:
                return element.get_text(separator=' ', strip=True)
        
        # Fallback: get main content
        article = soup.find('article') or soup.find('main') or soup
        return article.get_text(separator=' ', strip=True)[:2000]  # Limit length
    
    def _extract_requirements(self, soup: BeautifulSoup, description: str) -> List[str]:
        """Extract job requirements and qualifications"""
        requirements = []
        
        # Look for requirement sections
        requirement_patterns = [
            r'(?:Requirements?|Qualifications?|Skills?|Must have)[:\s]*([^.]+)',
            r'(?:You will need|We are looking for|Ideal candidate)[:\s]*([^.]+)',
            r'(?:Essential|Required|Mandatory)[:\s]*([^.]+)'
        ]
        
        for pattern in requirement_patterns:
            matches = re.findall(pattern, description, re.IGNORECASE)
            requirements.extend([req.strip() for req in matches if len(req.strip()) > 10])
        
        # Extract bullet points
        bullet_elements = soup.find_all(['li', 'p'])
        for element in bullet_elements:
            text = element.get_text(strip=True)
            if any(keyword in text.lower() for keyword in ['experience', 'skill', 'knowledge', 'degree', 'certification']):
                if 20 < len(text) < 200:  # Reasonable length
                    requirements.append(text)
        
        return list(set(requirements))[:10]  # Limit and deduplicate
    
    def _extract_salary(self, soup: BeautifulSoup, description: str) -> Optional[str]:
        """Extract salary information"""
        salary_patterns = [
            r'\$[\d,]+(?:\s*-\s*\$[\d,]+)?(?:\s*(?:per\s+year|annually|pa))?',
            r'[\d,]+k?\s*-\s*[\d,]+k?\s*(?:per\s+year|annually|pa)',
            r'Salary:?\s*([^.\n]+)'
        ]
        
        text_content = soup.get_text()
        for pattern in salary_patterns:
            match = re.search(pattern, text_content, re.IGNORECASE)
            if match:
                return match.group(0).strip()
        
        return None
    
    def _extract_location(self, soup: BeautifulSoup) -> Optional[str]:
        """Extract job location"""
        location_selectors = [
            '[data-automation="job-detail-location"]',
            '.location',
            '.job-location',
            '[data-testid="location"]'
        ]
        
        for selector in location_selectors:
            element = soup.select_one(selector)
            if element:
                return element.get_text(strip=True)
        
        return None
    
    def _extract_job_type(self, soup: BeautifulSoup, description: str) -> Optional[str]:
        """Extract job type (full-time, part-time, contract)"""
        job_type_patterns = [
            r'\b(full-time|part-time|contract|temporary|permanent|casual)\b'
        ]
        
        text_content = soup.get_text().lower()
        for pattern in job_type_patterns:
            match = re.search(pattern, text_content)
            if match:
                return match.group(1).title()
        
        return None
    
    def _extract_industry(self, soup: BeautifulSoup, company_name: str) -> Optional[str]:
        """Extract industry information"""
        # This could be enhanced with external APIs or ML models
        industry_keywords = {
            'technology': ['software', 'tech', 'digital', 'IT', 'computer'],
            'finance': ['bank', 'finance', 'investment', 'accounting'],
            'healthcare': ['health', 'medical', 'hospital', 'pharmaceutical'],
            'education': ['university', 'school', 'education', 'academic'],
            'retail': ['retail', 'store', 'shop', 'commerce'],
        }
        
        text_content = (soup.get_text() + ' ' + company_name).lower()
        
        for industry, keywords in industry_keywords.items():
            if any(keyword in text_content for keyword in keywords):
                return industry.title()
        
        return None

class CoverLetterGenerator:
    """Enhanced cover letter generation with templates and AI"""
    
    def __init__(self):
        self.templates = self._load_templates()
    
    def _load_templates(self) -> Dict[str, Template]:
        """Load Jinja2 templates for different styles"""
        templates = {}
        
        # Professional template
        professional_template = """
Dear Hiring Manager at {{ company_name }},

I am writing to express my strong interest in the {{ job_title }} position at {{ company_name }}. With {{ experience_years }} years of experience in the field and a {{ degree }} degree, I am confident that my background aligns perfectly with your requirements.

Throughout my career, I have developed expertise in {{ skills | join(', ') }}, which directly relates to the qualifications you are seeking. {% if previous_roles %}In my previous roles as {{ previous_roles | join(' and ') }}, {% endif %}I have consistently demonstrated my ability to deliver results and drive innovation.

{% if achievements %}Some of my key achievements include:
{% for achievement in achievements %}
• {{ achievement }}
{% endfor %}
{% endif %}

What particularly attracts me to {{ company_name }} is {{ attraction_reason }}. I am excited about the opportunity to contribute to your team and help drive {{ company_name }}'s continued success.

{% if custom_message %}
{{ custom_message }}
{% endif %}

Thank you for considering my application. I look forward to the opportunity to discuss how my skills and experience can benefit {{ company_name }}.

Sincerely,
{{ name }}
{{ email }}
{{ phone }}
{% if linkedin_url %}LinkedIn: {{ linkedin_url }}{% endif %}
{% if portfolio_url %}Portfolio: {{ portfolio_url }}{% endif %}
"""

        # Creative template
        creative_template = """
Hello {{ company_name }} Team!

I'm {{ name }}, and I'm thrilled about the {{ job_title }} opportunity at {{ company_name }}! 

Your job posting caught my attention because {{ attraction_reason }}. With {{ experience_years }} years of experience and a passion for {{ skills[:3] | join(', ') }}, I believe I can bring fresh perspectives and innovative solutions to your team.

Here's what I bring to the table:
• {{ degree }} degree with hands-on experience in {{ skills | join(', ') }}
{% if previous_roles %}• Proven track record in {{ previous_roles | join(' and ') }}{% endif %}
{% if achievements %}{% for achievement in achievements %}• {{ achievement }}
{% endfor %}{% endif %}

I'm not just looking for any job – I'm looking for the RIGHT opportunity where I can make a meaningful impact. {{ company_name }} represents exactly that kind of environment where innovation meets execution.

{% if custom_message %}
{{ custom_message }}
{% endif %}

I'd love to chat more about how we can create something amazing together!

Best regards,
{{ name }}
{{ email }} | {{ phone }}
{% if linkedin_url %}LinkedIn: {{ linkedin_url }}{% endif %}
"""

        # Technical template
        technical_template = """
Dear {{ company_name }} Engineering Team,

I am applying for the {{ job_title }} position with {{ experience_years }} years of specialized experience in software development and technical problem-solving.

Technical Expertise:
{% for skill in skills %}
• {{ skill }}
{% endfor %}

Professional Background:
{% if previous_roles %}{% for role in previous_roles %}
• {{ role }}
{% endfor %}{% endif %}

Key Technical Achievements:
{% if achievements %}{% for achievement in achievements %}
• {{ achievement }}
{% endfor %}{% endif %}

I am particularly interested in {{ company_name }} because of {{ attraction_reason }}. Your technical challenges align perfectly with my experience and career goals.

{% if custom_message %}
Technical Note: {{ custom_message }}
{% endif %}

I would welcome the opportunity to discuss the technical aspects of this role in detail.

Best regards,
{{ name }}
Technical Contact: {{ email }}
{% if portfolio_url %}Portfolio/GitHub: {{ portfolio_url }}{% endif %}
"""

        templates['professional'] = Template(professional_template)
        templates['creative'] = Template(creative_template)
        templates['technical'] = Template(technical_template)
        
        return templates
    
    def generate_cover_letter(self, job_details: JobDetails, user_profile: UserProfile, 
                            style: str = "professional", custom_message: Optional[str] = None) -> str:
        """Generate personalized cover letter"""
        
        # Determine attraction reason based on job details
        attraction_reason = self._generate_attraction_reason(job_details)
        
        template_vars = {
            'company_name': job_details.company_name,
            'job_title': job_details.job_title,
            'name': user_profile.name,
            'email': user_profile.email,
            'phone': user_profile.phone,
            'experience_years': user_profile.experience_years,
            'degree': user_profile.degree,
            'skills': user_profile.skills,
            'previous_roles': user_profile.previous_roles,
            'achievements': user_profile.achievements,
            'linkedin_url': user_profile.linkedin_url,
            'portfolio_url': user_profile.portfolio_url,
            'attraction_reason': attraction_reason,
            'custom_message': custom_message
        }
        
        template = self.templates.get(style, self.templates['professional'])
        return template.render(**template_vars)
    
    def _generate_attraction_reason(self, job_details: JobDetails) -> str:
        """Generate personalized attraction reason based on job details"""
        reasons = [
            f"your reputation for innovation in the {job_details.industry or 'industry'}",
            f"the challenging nature of the {job_details.job_title} role",
            "your company's commitment to excellence and growth",
            f"the opportunity to work with cutting-edge technologies in {job_details.industry or 'your field'}",
            "your company's collaborative culture and team-oriented approach"
        ]
        
        # Select based on job details
        if job_details.industry:
            return reasons[0]
        elif "senior" in job_details.job_title.lower() or "lead" in job_details.job_title.lower():
            return reasons[1]
        else:
            return reasons[2]

# FastAPI app with lifespan management
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting Job Application Generator Service")
    yield
    logger.info("Shutting down Job Application Generator Service")

app = FastAPI(
    title="AI-Powered Job Application Generator",
    description="Generate personalized cover letters and applications by analyzing job postings",
    version="2.0.0",
    lifespan=lifespan
)

# Mount static files
app.mount("/static", StaticFiles(directory=str(OUTPUT_DIR)), name="static")

# Global instances
cover_letter_generator = CoverLetterGenerator()

@app.get("/", response_class=HTMLResponse)
async def get_home_page():
    """Serve the main application page"""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>AI Job Application Generator</title>
        <style>
            * {
                margin: 0;
                padding: 0;
                box-sizing: border-box;
            }
            
            body {
                font-family: 'Segoe UI', Tahoma, Geneva, Verdana, sans-serif;
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                min-height: 100vh;
                padding: 20px;
            }
            
            .container {
                max-width: 1200px;
                margin: 0 auto;
                background: white;
                border-radius: 20px;
                padding: 40px;
                box-shadow: 0 25px 50px rgba(0,0,0,0.15);
            }
            
            h1 {
                text-align: center;
                color: #333;
                margin-bottom: 10px;
                font-size: 2.5em;
                font-weight: 700;
            }
            
            .subtitle {
                text-align: center;
                color: #666;
                margin-bottom: 40px;
                font-size: 1.2em;
            }
            
            .form-section {
                background: #f8f9ff;
                padding: 30px;
                border-radius: 15px;
                margin-bottom: 30px;
                border-left: 5px solid #667eea;
            }
            
            .form-section h2 {
                color: #333;
                margin-bottom: 20px;
                font-size: 1.5em;
            }
            
            .form-grid {
                display: grid;
                grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
                gap: 20px;
            }
            
            .form-group {
                display: flex;
                flex-direction: column;
            }
            
            label {
                font-weight: 600;
                color: #333;
                margin-bottom: 8px;
            }
            
            input, select, textarea {
                padding: 12px;
                border: 2px solid #e0e0e0;
                border-radius: 8px;
                font-size: 16px;
                transition: border-color 0.3s ease;
            }
            
            input:focus, select:focus, textarea:focus {
                outline: none;
                border-color: #667eea;
                box-shadow: 0 0 0 3px rgba(102, 126, 234, 0.1);
            }
            
            .skills-input {
                margin-bottom: 10px;
            }
            
            .skills-tags {
                display: flex;
                flex-wrap: wrap;
                gap: 8px;
                margin-top: 10px;
            }
            
            .skill-tag {
                background: #667eea;
                color: white;
                padding: 6px 12px;
                border-radius: 20px;
                font-size: 14px;
                display: flex;
                align-items: center;
                gap: 8px;
            }
            
            .skill-tag .remove {
                cursor: pointer;
                background: rgba(255,255,255,0.3);
                border-radius: 50%;
                width: 18px;
                height: 18px;
                display: flex;
                align-items: center;
                justify-content: center;
                font-size: 12px;
            }
            
            .generate-btn {
                background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
                color: white;
                padding: 15px 40px;
                border: none;
                border-radius: 25px;
                font-size: 18px;
                font-weight: 600;
                cursor: pointer;
                transition: transform 0.3s ease;
                display: block;
                margin: 30px auto;
                min-width: 250px;
            }
            
            .generate-btn:hover {
                transform: translateY(-2px);
                box-shadow: 0 15px 30px rgba(102, 126, 234, 0.4);
            }
            
            .generate-btn:disabled {
                opacity: 0.6;
                cursor: not-allowed;
                transform: none;
            }
            
            .loading {
                display: none;
                text-align: center;
                margin: 20px 0;
            }
            
            .spinner {
                border: 4px solid #f3f3f3;
                border-top: 4px solid #667eea;
                border-radius: 50%;
                width: 40px;
                height: 40px;
                animation: spin 1s linear infinite;
                margin: 0 auto 20px;
            }
            
            @keyframes spin {
                0% { transform: rotate(0deg); }
                100% { transform: rotate(360deg); }
            }
            
            .result {
                display: none;
                background: #f8f9fa;
                padding: 30px;
                border-radius: 15px;
                margin-top: 30px;
                border-left: 5px solid #28a745;
            }
            
            .result h3 {
                color: #28a745;
                margin-bottom: 20px;
            }
            
            .download-links {
                display: flex;
                gap: 15px;
                flex-wrap: wrap;
            }
            
            .download-btn {
                background: #28a745;
                color: white;
                padding: 10px 20px;
                text-decoration: none;
                border-radius: 8px;
                transition: background 0.3s ease;
            }
            
            .download-btn:hover {
                background: #218838;
            }
            
            .error {
                background: #f8d7da;
                color: #721c24;
                padding: 20px;
                border-radius: 8px;
                margin: 20px 0;
                border-left: 5px solid #dc3545;
                display: none;
            }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>🚀 AI Job Application Generator</h1>
            <p class="subtitle">Generate personalized cover letters by analyzing any job posting URL</p>
            
            <form id="applicationForm">
                <div class="form-section">
                    <h2>📋 Job Information</h2>
                    <div class="form-group">
                        <label for="jobUrl">Job Posting URL *</label>
                        <input type="url" id="jobUrl" name="jobUrl" required 
                               placeholder="https://example.com/job-posting">
                    </div>
                    <div class="form-group">
                        <label for="coverLetterStyle">Cover Letter Style</label>
                        <select id="coverLetterStyle" name="coverLetterStyle">
                            <option value="professional">Professional</option>
                            <option value="creative">Creative</option>
                            <option value="technical">Technical</option>
                        </select>
                    </div>
                </div>
                
                <div class="form-section">
                    <h2>👤 Personal Information</h2>
                    <div class="form-grid">
                        <div class="form-group">
                            <label for="name">Full Name *</label>
                            <input type="text" id="name" name="name" required>
                        </div>
                        <div class="form-group">
                            <label for="email">Email Address *</label>
                            <input type="email" id="email" name="email" required>
                        </div>
                        <div class="form-group">
                            <label for="phone">Phone Number *</label>
                            <input type="tel" id="phone" name="phone" required>
                        </div>
                        <div class="form-group">
                            <label for="linkedin">LinkedIn Profile (Optional)</label>
                            <input type="url" id="linkedin" name="linkedin">
                        </div>
                    </div>
                </div>
                
                <div class="form-section">
                    <h2>🎓 Professional Background</h2>
                    <div class="form-grid">
                        <div class="form-group">
                            <label for="experience">Years of Experience *</label>
                            <input type="number" id="experience" name="experience" min="0" max="50" required>
                        </div>
                        <div class="form-group">
                            <label for="degree">Highest Degree *</label>
                            <input type="text" id="degree" name="degree" required 
                                   placeholder="Bachelor's in Computer Science">
                        </div>
                    </div>
                    
                    <div class="form-group">
                        <label for="skills">Skills (Press Enter to add) *</label>
                        <input type="text" id="skills" name="skills" class="skills-input" 
                               placeholder="Type a skill and press Enter">
                        <div class="skills-tags" id="skillsTags"></div>
                    </div>
                    
                    <div class="form-group">
                        <label for="previousRoles">Previous Job Titles (Optional)</label>
                        <input type="text" id="previousRoles" name="previousRoles" 
                               placeholder="Software Engineer, Project Manager (comma separated)">
                    </div>
                    
                    <div class="form-group">
                        <label for="achievements">Key Achievements (Optional)</label>
                        <textarea id="achievements" name="achievements" rows="4"
                                  placeholder="List your key achievements (one per line)"></textarea>
                    </div>
                </div>
                
                <div class="form-section">
                    <h2>✨ Customization</h2>
                    <div class="form-group">
                        <label for="customMessage">Custom Message (Optional)</label>
                        <textarea id="customMessage" name="customMessage" rows="3"
                                  placeholder="Any specific message you'd like to include"></textarea>
                    </div>
                </div>
                
                <button type="submit" class="generate-btn" id="generateBtn">
                    Generate Application
                </button>
            </form>
            
            <div class="loading" id="loading">
                <div class="spinner"></div>
                <p>Analyzing job posting and generating your personalized application...</p>
            </div>
            
            <div class="error" id="error"></div>
            
            <div class="result" id="result">
                <h3>✅ Application Generated Successfully!</h3>
                <div id="resultContent"></div>
                <div class="download-links" id="downloadLinks"></div>
            </div>
        </div>
        
        <script>
            let skills = [];
            
            // Skills management
            document.getElementById('skills').addEventListener('keypress', function(e) {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    const skill = this.value.trim();
                    if (skill && !skills.includes(skill)) {
                        skills.push(skill);
                        updateSkillsTags();
                        this.value = '';
                    }
                }
            });
            
            function updateSkillsTags() {
                const container = document.getElementById('skillsTags');
                container.innerHTML = '';
                
                skills.forEach((skill, index) => {
                    const tag = document.createElement('div');
                    tag.className = 'skill-tag';
                    tag.innerHTML = `
                        ${skill}
                        <span class="remove" onclick="removeSkill(${index})">×</span>
                    `;
                    container.appendChild(tag);
                });
            }
            
            function removeSkill(index) {
                skills.splice(index, 1);
                updateSkillsTags();
            }
            
            // Form submission
            document.getElementById('applicationForm').addEventListener('submit', async function(e) {
                e.preventDefault();
                
                if (skills.length === 0) {
                    showError('Please add at least one skill');
                    return;
                }
                
                const formData = new FormData(this);
                const data = {
                    job_url: formData.get('jobUrl'),
                    user_profile: {
                        name: formData.get('name'),
                        email: formData.get('email'),
                        phone: formData.get('phone'),
                        experience_years: parseInt(formData.get('experience')),
                        degree: formData.get('degree'),
                        skills: skills,
                        previous_roles: formData.get('previousRoles') ? 
                            formData.get('previousRoles').split(',').map(s => s.trim()) : [],
                        achievements: formData.get('achievements') ? 
                            formData.get('achievements').split('\\n').filter(a => a.trim()) : [],
                        linkedin_url: formData.get('linkedin') || null
                    },
                    cover_letter_style: formData.get('coverLetterStyle'),
                    custom_message: formData.get('customMessage') || null
                };
                
                showLoading();
                hideError();
                hideResult();
                
                try {
                    const response = await fetch('/generate-application', {
                        method: 'POST',
                        headers: {
                            'Content-Type': 'application/json'
                        },
                        body: JSON.stringify(data)
                    });
                    
                    const result = await response.json();
                    
                    if (result.success) {
                        showResult(result);
                    } else {
                        showError(result.message || 'Failed to generate application');
                    }
                } catch (error) {
                    showError('Network error: ' + error.message);
                } finally {
                    hideLoading();
                }
            });
            
            function showLoading() {
                document.getElementById('loading').style.display = 'block';
                document.getElementById('generateBtn').disabled = true;
            }
            
            function hideLoading() {
                document.getElementById('loading').style.display = 'none';
                document.getElementById('generateBtn').disabled = false;
            }
            
            function showError(message) {
                const errorDiv = document.getElementById('error');
                errorDiv.textContent = message;
                errorDiv.style.display = 'block';
            }
            
            function hideError() {
                document.getElementById('error').style.display = 'none';
            }
            
            function showResult(result) {
                const resultDiv = document.getElementById('result');
                const contentDiv = document.getElementById('resultContent');
                const linksDiv = document.getElementById('downloadLinks');
                
                contentDiv.innerHTML = `
                    <p><strong>Company:</strong> ${result.company_name}</p>
                    <p><strong>Position:</strong> ${result.job_title}</p>
                    <p><strong>Application ID:</strong> ${result.application_id}</p>
                `;
                
                linksDiv.innerHTML = '';
                if (result.cover_letter_path) {
                    const link = document.createElement('a');
                    link.href = '/download/' + result.application_id + '/cover-letter';
                    link.className = 'download-btn';
                    link.textContent = '📄 Download Cover Letter';
                    linksDiv.appendChild(link);
                }
                
                resultDiv.style.display = 'block';
            }
            
            function hideResult() {
                document.getElementById('result').style.display = 'none';
            }
        </script>
    </body>
    </html>
    """
    return html_content

@app.post("/generate-application", response_model=ApplicationResponse)
async def generate_application(request: JobApplicationRequest, background_tasks: BackgroundTasks):
    """Generate a personalized job application"""
    application_id = str(uuid.uuid4())
    
    try:
        async with WebScraper() as scraper:
            # Fetch and parse job posting
            html_content = await scraper.fetch_html(str(request.job_url))
            if not html_content:
                raise HTTPException(status_code=400, detail="Failed to fetch job posting")
            
            job_details = scraper.extract_job_details(html_content, str(request.job_url))
            
            # Generate cover letter
            cover_letter = cover_letter_generator.generate_cover_letter(
                job_details=job_details,
                user_profile=request.user_profile,
                style=request.cover_letter_style,
                custom_message=request.custom_message
            )
            
            # Save cover letter
            cover_letter_filename = f"{application_id}_cover_letter.txt"
            cover_letter_path = OUTPUT_DIR / cover_letter_filename
            
            async with aiofiles.open(cover_letter_path, 'w', encoding='utf-8') as f:
                await f.write(cover_letter)
            
            # Save application metadata
            metadata = {
                "application_id": application_id,
                "timestamp": datetime.now().isoformat(),
                "job_details": job_details.dict(),
                "user_profile": request.user_profile.dict(),
                "cover_letter_style": request.cover_letter_style,
                "custom_message": request.custom_message
            }
            
            metadata_path = OUTPUT_DIR / f"{application_id}_metadata.json"
            async with aiofiles.open(metadata_path, 'w', encoding='utf-8') as f:
                await f.write(json.dumps(metadata, indent=2))
            
            logger.info(f"Generated application {application_id} for {job_details.company_name}")
            
            return ApplicationResponse(
                success=True,
                application_id=application_id,
                company_name=job_details.company_name,
                job_title=job_details.job_title,
                cover_letter_path=cover_letter_filename,
                message=f"Successfully generated application for {job_details.job_title} at {job_details.company_name}"
            )
            
    except Exception as e:
        logger.error(f"Error generating application: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to generate application: {str(e)}")

@app.get("/download/{application_id}/cover-letter")
async def download_cover_letter(application_id: str):
    """Download generated cover letter"""
    cover_letter_path = OUTPUT_DIR / f"{application_id}_cover_letter.txt"
    
    if not cover_letter_path.exists():
        raise HTTPException(status_code=404, detail="Cover letter not found")
    
    return FileResponse(
        path=cover_letter_path,
        filename=f"cover_letter_{application_id}.txt",
        media_type="text/plain"
    )

@app.get("/applications")
async def list_applications():
    """List all generated applications"""
    applications = []
    
    for metadata_file in OUTPUT_DIR.glob("*_metadata.json"):
        try:
            async with aiofiles.open(metadata_file, 'r', encoding='utf-8') as f:
                content = await f.read()
                metadata = json.loads(content)
                applications.append({
                    "application_id": metadata["application_id"],
                    "timestamp": metadata["timestamp"],
                    "company_name": metadata["job_details"]["company_name"],
                    "job_title": metadata["job_details"]["job_title"],
                    "applicant_name": metadata["user_profile"]["name"]
                })
        except Exception as e:
            logger.error(f"Error reading metadata file {metadata_file}: {e}")
    
    return {"applications": sorted(applications, key=lambda x: x["timestamp"], reverse=True)}

@app.delete("/applications/{application_id}")
async def delete_application(application_id: str):
    """Delete a generated application"""
    files_to_delete = [
        OUTPUT_DIR / f"{application_id}_cover_letter.txt",
        OUTPUT_DIR / f"{application_id}_metadata.json"
    ]
    
    deleted_files = []
    for file_path in files_to_delete:
        if file_path.exists():
            file_path.unlink()
            deleted_files.append(file_path.name)
    
    if not deleted_files:
        raise HTTPException(status_code=404, detail="Application not found")
    
    return {"message": f"Deleted application {application_id}", "deleted_files": deleted_files}

@app.get("/job-preview")
async def preview_job_details(url: HttpUrl):
    """Preview job details without generating application"""
    try:
        async with WebScraper() as scraper:
            html_content = await scraper.fetch_html(str(url))
            if not html_content:
                raise HTTPException(status_code=400, detail="Failed to fetch job posting")
            
            job_details = scraper.extract_job_details(html_content, str(url))
            return job_details
            
    except Exception as e:
        logger.error(f"Error previewing job: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to preview job: {str(e)}")

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:app",
        host="0.0.0.0",
        port=8020,
        reload=True,
        log_level="info"
    )
