import requests
from bs4 import BeautifulSoup
import re
import nltk

nltk.download('punkt')

def fetch_html(url):
    """Fetch HTML content from the specified URL."""
    try:
        response = requests.get(url)
        response.raise_for_status()  # Raise an error for bad responses
        return response.content
    except requests.RequestException as e:
        print(f"Error fetching URL: {e}")
        return None

def extract_company_and_title(soup):
    """Extract the company name and job title from the BeautifulSoup object."""
    article = soup.find('article')
    article_text = article.text if article else ''
    
    company_name_regex = re.compile(r'(?:[^\w]|^)(?P<company>[A-Z][\w&\']*(\s+[A-Z][\w&\']*)*)(?=[^\w]|$)')
    match = company_name_regex.search(article_text)
    
    company_name = match.group('company') if match else soup.title.string.strip()
    job_title = soup.find('h1').text.strip()
    
    return company_name, job_title

def create_cover_letter(company_name, job_title, experience, degree, skills, name, email, phone):
    """Create the body of the cover letter."""
    paragraphs = [
        f"Dear Hiring Manager at {company_name},",
        f"I am excited to apply for the position of {job_title}. "
        f"I believe my experience and skills make me a perfect fit for this role.",
        f"I have {experience} years of experience in the field, and a {degree} degree in a related field. "
        f"I am confident that my skills in {', '.join(skills)} would be an asset to {company_name}.",
        "In my current position, I have demonstrated my ability to work well in a team and independently, "
        "as well as my strong problem-solving skills. I have consistently exceeded targets and contributed to "
        "the growth of the company.",
        f"I am particularly interested in working at {company_name} because of the company's commitment to "
        "innovation and the opportunity to work with a team of experts in the field. I am excited about "
        "the potential to contribute to the company's growth and success. "
        "I am confident that I would thrive in the company's dynamic and collaborative environment.",
        "Thank you for considering my application. Please find attached my CV for your review.",
        "Sincerely,",
        name,
        email,
        phone
    ]
    
    return "\n\n".join(paragraphs)

def generate_cv(url, name, email, phone, experience, degree, skills):
    """Generate a CV based on job posting details."""
    html_content = fetch_html(url)
    if html_content is None:
        return "Failed to fetch job details."

    soup = BeautifulSoup(html_content, 'html.parser')
    company_name, job_title = extract_company_and_title(soup)
    
    cv = create_cover_letter(company_name, job_title, experience, degree, skills, name, email, phone)
    
    with open(f"{name}.txt", "w") as f:
        f.write(cv)
        
    return cv

# Example usage (commented out)
# generate_cv("https://example.com/job-posting", "John Doe", "john@example.com", "123-456-7890", 5, "Bachelor's", ["Python", "SQL", "Machine Learning"])
