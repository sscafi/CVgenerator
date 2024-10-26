import requests
from bs4 import BeautifulSoup
import re
import nltk
nltk.download('punkt')

def generate_cv(url, name, email, phone, experience, degree, skills):
    # Get the HTML content from the URL
    response = requests.get(url)
    soup = BeautifulSoup(response.content, 'html.parser')
    
    # Extract the company name and job title
    article = soup.find('article')
    if article is not None:
        article_text = article.text
    else:
        article_text = ''
    company_name_regex = re.compile(r'(?:[^\w]|^)(?P<company>[A-Z][\w&\']*(\s+[A-Z][\w&\']*)*)(?=[^\w]|$)')
    match = company_name_regex.search(article_text)
    if match:
        company_name = match.group('company')
    else:
        company_name = soup.title.string.strip()
    job_title = soup.find('h1').text.strip()
    
    # Create the body of the cover letter
    paragraphs = []
    paragraphs.append(f"Dear Hiring Manager at {company_name},")
    paragraphs.append("I am excited to apply for the position of " + job_title + ". " +
                      "I believe my experience and skills make me a perfect fit for this role.")
    paragraphs.append(f"I have {experience} years of experience in the field, and a {degree} degree in a related field. " +
                      f"I am confident that my skills in {', '.join(skills)} would be an asset to {company_name}.")
    paragraphs.append("In my current position, I have demonstrated my ability to work well in a team and independently, " +
                      "as well as my strong problem-solving skills. I have consistently exceeded targets and contributed to " +
                      "the growth of the company.")
    paragraphs.append(f"I am particularly interested in working at {company_name} because of the company's commitment to " +
                      "innovation and the opportunity to work with a team of experts in the field. I am excited about " +
                      "the potential to contribute to the company's growth and success. " +
                      "I am confident that I would thrive in the company's dynamic and collaborative environment.")
    paragraphs.append("Thank you for considering my application. Please find attached my CV for your review.")
    paragraphs.append("Sincerely,")
    paragraphs.append(name)
    paragraphs.append(email)
    paragraphs.append(phone)

    # Join the paragraphs into a single string with line breaks between them
    cv = "\n\n".join(paragraphs)
    
    with open(f"{name}.txt", "w") as f:
        f.write(cv)
        
    return cv