
import requests
from bs4 import BeautifulSoup
import PyPDF2
import io
import pandas as pd
import re
import time
import socket
from IPython.display import display


base_url = "https://www.justiceinspectorates.gov.uk/hmiprobation/inspections"

# requests (hide behind legit web use)
headers = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/114.0.0.0 Safari/537.36"
}

# get soup object from URL
def get_soup(url, max_attempts=5, delay=2):
    for attempt in range(1, max_attempts + 1):
        try:
            response = requests.get(url, headers=headers, timeout=10)
            response.raise_for_status()
            return BeautifulSoup(response.content, "html.parser")
        except requests.RequestException as e:
            if attempt < max_attempts:
                time.sleep(delay)
            else:
                return None

def normalise_text(text):
    return " ".join(text.lower().split())


def extract_ratings_from_pdf(pdf_url):
    try:
        response = requests.get(pdf_url, headers=headers, timeout=15)
        response.raise_for_status()
        pdf_file = io.BytesIO(response.content)
        reader = PyPDF2.PdfReader(pdf_file)
    except (requests.RequestException, PyPDF2.errors.PdfReadError) as e:
        print(f"Failed to read PDF {pdf_url}: {e}")
        return "Ratings page not found"

    ratings_text = ""
    for page in reader.pages[2:]:
        text = page.extract_text()
        if text and "Ratings" in text:
            ratings_text += text
            break  

    return ratings_text if ratings_text else "Ratings page not found"


def parse_ratings(report_url, ratings_text):
    lines = ratings_text.split("\n")
    report_name = None
    overall_rating = None
    score = None  
    graded_outcomes = {}

    grading_outcomes = {"inadequate", "requires improvement", "good", "outstanding"}

    # clean report/la names
    words_to_remove = {"inspection", "of", "probation", "services", ":", "prevention", "region", "services in", "pdu", "youth", "justice", "service"}

    for i, line in enumerate(lines):
        line = re.sub(r"\s+", " ", line).strip()

        # report name (first valid line excluding keywords)
        if report_name is None and line and "Ratings" not in line and "Fieldwork started" not in line and "Overall rating" not in line:
            report_name = line

        # Capture overall rating
        if "Overall rating" in line:
            overall_rating = line.split("Overall rating")[-1].strip()

# # REturn the raw string based fraction grading as XX/YY
#         # Capture score (format: number/number)
#         score_match = re.search(r"\b(\d{1,2}/\d{1,2})\b", line)  # locate number/number score 
#         if score_match and score is None:
#             score = score_match.group(1) # return raw string based fraction grading as XX/YY
       
        # return % value as likely more useful down the line
        score_match = re.search(r"\b(\d+)/(\d+)\b", line)  # locate number/number score 
        if score_match and score is None:
            try:
                numerator, denominator = map(int, score_match.groups())
                if denominator > 0:  # no division by zero
                    score = round((numerator / denominator) * 100, 2)
            except ValueError:
                print(f"Error parsing score in: {line}")  # debug
                
    # Clean report name
    if report_name:
        report_name = re.sub(r"\s+", " ", report_name).strip()  # normalise problematic spacing (common!)
        report_name = re.sub(r"\d+", "", report_name).strip() # remove all numeric elements

        report_name_words = report_name.split()
        report_name = " ".join([word for word in report_name_words if word.lower() not in words_to_remove]).strip()

    cleaned_lines = [re.sub(r"\s+", " ", line).strip() for line in lines if line.strip()]

    for line in cleaned_lines:
        match = re.match(r"^[PR]?\s*(\d+\.\d+)\s(.+?)\s(\w+)$", line)
        if match:
            category_name = match.group(2).strip()
            grade = match.group(3).capitalize()

            if grade.lower() in grading_outcomes:
                graded_outcomes[category_name] = grade

    record = {
        "LA_name": report_name if report_name else "Unknown",
        "Score (%)": score if score else "N/A",  
        "Overall Rating": overall_rating,
        "Report URL": report_url
    }
    record.update(graded_outcomes)

    return record



# pagination through inspection links
inspection_links = []
page = 0

while True:
    paginated_url = f"{base_url}?page={page}"
    soup = get_soup(paginated_url)

    if not soup:
        print(f"Reached an invalid page ({page}). Assuming end of pagination.")
        break

    found_links = 0

    for link in soup.find_all("a", href=True):
        if "inspection" in normalise_text(link.text):
            inspection_links.append(link["href"])
            found_links += 1

    if found_links == 0:
        print(f"No more inspection links found on page {page}. Ending pagination.")
        break

    print(f"Processed Page {page}: Found {found_links} new inspection links.")
    
    page += 1
    time.sleep(2)
    
#     # testing limiter
#     if page > 10:  # Debug
#         break

# PDF links
pdf_links = {}

for inspection_link in inspection_links:
    full_inspection_url = inspection_link if inspection_link.startswith("http") else base_url + inspection_link
    soup = get_soup(full_inspection_url)

    if not soup:
        continue

    for pdf_link in soup.find_all("a", href=True):
        if "inspection" in normalise_text(pdf_link.text) and pdf_link["href"].endswith(".pdf"):
            pdf_links[full_inspection_url] = pdf_link["href"]
            
            # filter known not-required links by keyword
            filtered_pdf_links = {url: pdf_url for url, pdf_url in pdf_links.items() if "thematic" not in pdf_url.lower()}
#             print(f"Filtered out {len(pdf_links) - len(filtered_pdf_links)} thematic reports.")
            
            pdf_links = filtered_pdf_links
            break  

     
            
# ratings data from PDFs
ratings_data = {}

for inspection_url, pdf_url in pdf_links.items():
    print(f"Extracting Ratings from: {pdf_url}")
    ratings_text = extract_ratings_from_pdf(pdf_url)
    ratings_data[inspection_url] = ratings_text[:1000]


combined_structured_data = [parse_ratings(url, text) for url, text in ratings_data.items()]


combined_structured_data_df = pd.DataFrame(combined_structured_data)

combined_structured_data_df = combined_structured_data_df.loc[:, ~combined_structured_data_df.columns.duplicated()]


# bit simple brute force here, to refactor later
combined_structured_data_df.columns = combined_structured_data_df.columns.str.replace(" ", "", regex=True)
combined_structured_data_df.columns = combined_structured_data_df.columns.str.strip().str.replace(r"[^\w\s]", "", regex=True).str.replace(r"\s+", " ", regex=True)

combined_structured_data_df["CombinedStaff"] = combined_structured_data_df[["Staff", "Staffing"]].bfill(axis=1).iloc[:, 0]
combined_structured_data_df["CombinedLeadership"] = combined_structured_data_df[["Leadership", "Governanceandleadership"]].bfill(axis=1).iloc[:, 0]
combined_structured_data_df["CombinedVictimWork"] = combined_structured_data_df[["Statutoryvictimwork", "Victimwork"]].bfill(axis=1).iloc[:, 0]
combined_structured_data_df["CombinedResettlement"] = combined_structured_data_df[["Resettlement", "Resettlementpolicyandprovision"]].bfill(axis=1).iloc[:, 0]


combined_structured_data_df.drop(columns=["Staff", "Staffing"], inplace=True)
combined_structured_data_df.drop(columns=["Leadership", "Governanceandleadership"], inplace=True)
combined_structured_data_df.drop(columns=["Statutoryvictimwork", "Victimwork"], inplace=True)
combined_structured_data_df.drop(columns=["Resettlement", "Resettlementpolicyandprovision"], inplace=True)


combined_structured_data_df.to_csv("probation_and_youthjustice_ratings.csv", index=False)

display(combined_structured_data_df)