# aged_care_scraper.py
# prior to running this script, ensure playright is setup
# this was executed in a wsl environment using chromiu
# python -m playwright install chromium
# python -m playwright install-deps


# aged_care_scraper.py
import time
import os
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import pandas as pd
import json
import urllib.parse
import uuid

def extract_providers_from_html(html_content, base_url="https://www.myagedcare.gov.au"):
    """Extract aged care provider information from HTML content using BeautifulSoup"""
    soup = BeautifulSoup(html_content, 'html.parser')
    
    # Find all provider cards using the correct custom element
    provider_cards = soup.find_all('mac-provider-result-card')
    
    providers = []
    
    for card in provider_cards:
        try:
            # Extract provider name
            name_element = card.find('span', class_='text-style text-style--large text-style--weight--medium')
            name = name_element.text.strip() if name_element else "Unknown"
            
            # Extract location - it's in plain text after the location screenreader element
            location = "Unknown"
            location_marker = card.find('div', string='Location')
            if location_marker:
                # Look for the next text content after the location marker
                parent = location_marker.parent.parent.parent
                if parent:
                    location_text = parent.get_text()
                    # Extract location from the text (it's usually the first line after "Location")
                    lines = [line.strip() for line in location_text.split('\n') if line.strip()]
                    for line in lines:
                        if any(state in line for state in ['NSW', 'VIC', 'QLD', 'SA', 'WA', 'TAS', 'NT', 'ACT']):
                            location = line
                            break
            
            # Extract phone number
            phone = ""
            phone_element = card.find('mac-desktop-only')
            if phone_element:
                phone_text = phone_element.get_text()
                # Phone number is usually after location
                lines = [line.strip() for line in phone_text.split('\n') if line.strip()]
                for line in lines:
                    if any(char.isdigit() for char in line) and len(line.replace(' ', '')) >= 8:
                        phone = line
                        break
            
            # Extract star rating
            rating = 0
            rating_element = card.find('span', string=lambda text: text and 'Rating' in text and 'of 5' in text)
            if rating_element:
                rating_text = rating_element.text
                import re
                rating_match = re.search(r'Rating (\d+) of 5', rating_text)
                if rating_match:
                    rating = int(rating_match.group(1))
            
            # Extract provider link/ID
            link_element = card.find('a', href=True)
            provider_link = ""
            provider_id = ""
            if link_element:
                provider_link = link_element['href']
                if provider_link.startswith('/'):
                    provider_link = base_url + provider_link
                # Extract ID from URL
                import re
                id_match = re.search(r'/(\d+)\?', provider_link)
                if id_match:
                    provider_id = id_match.group(1)
            
            # Extract availability
            availability = "Unknown"
            availability_element = card.find('mac-availability')
            if availability_element:
                avail_text = availability_element.get_text()
                if 'Currently available' in avail_text:
                    availability = "Currently available"
                elif 'Not available' in avail_text:
                    availability = "Not available"
            
            # Extract room types
            room_types = []
            room_element = card.find('mac-match-tag')
            if room_element:
                room_text = room_element.get_text()
                if 'Matched' in room_text:
                    # Extract matched room types
                    lines = room_text.split(' - ')
                    for line in lines[1:]:  # Skip first part
                        if 'room' in line.lower():
                            room_types.append(line.strip())
            
            provider_data = {
                'id': provider_id,
                'name': name,
                'location': location,
                'phone': phone,
                'rating': rating,
                'availability': availability,
                'room_types': ', '.join(room_types) if room_types else "Unknown",
                'provider_link': provider_link,
                'scraped_at': time.strftime('%Y-%m-%d %H:%M:%S')
            }
            
            providers.append(provider_data)
            print(f"Extracted: {name} - {location}")
            
        except Exception as e:
            print(f"Error extracting provider data: {e}")
            continue
    
    return providers

def save_page_source(html, page_num, search_params, directory="html_pages"):
    """Save the page source to a file for debugging"""
    if not os.path.exists(directory):
        os.makedirs(directory)
    
    # Create filename with search parameters
    location_safe = "".join(c for c in search_params.get('location', 'unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
    care_type_safe = "".join(c for c in search_params.get('care_type', 'unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
    
    filename = os.path.join(directory, f"{location_safe}_{care_type_safe}_page_{page_num}.html")
    with open(filename, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"Saved page source to {filename}")

def build_search_url(search_params, start=0, rows=20):
    """Build the search URL with parameters"""
    base_url = "https://www.myagedcare.gov.au/find-a-provider/search-by-location"
    
    # Default parameters
    params = {
        'search': 'search-by-location',
        'careType': search_params.get('care_type', 'agedCareHomes'),
        'location': search_params.get('location', 'Sydney NSW 2000'),
        'roomType': search_params.get('room_type', 'dontMind'),
        'start': str(start),
        'rows': str(rows),
        'searchId': search_params.get('search_id', str(uuid.uuid4())[:10])  # Generate random search ID
    }
    
    # Build URL with parameters
    url_params = urllib.parse.urlencode(params)
    full_url = f"{base_url}?{url_params}"
    
    return full_url

def navigate_to_search_results(page, search_params, start=0, rows=20):
    """Navigate directly to search results using URL parameters"""
    search_url = build_search_url(search_params, start, rows)
    
    print(f"Navigating to: {search_url}")
    
    try:
        page.goto(search_url, wait_until="networkidle")
        
        # Wait for results to load - try multiple selectors
        selectors_to_try = [
            "mac-provider-result-card",
            ".provider-card", 
            ".search-results",
            "[data-provider-id]",
            ".card-action__content"
        ]
        
        found_selector = None
        for selector in selectors_to_try:
            try:
                page.wait_for_selector(selector, timeout=5000)
                found_selector = selector
                print(f"Found results using selector: {selector}")
                break
            except:
                continue
        
        if not found_selector:
            print("Warning: No provider cards found, but continuing...")
        
        return True
        
    except Exception as e:
        print(f"Error navigating to search results: {str(e)}")
        return False

def scrape_aged_care_providers(search_params, max_pages=50, save_html=True, debug=True, headless=True):
    """Use Playwright to scrape aged care provider data"""
    all_providers = []
    rows_per_page = 20  # Based on the URL parameter
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=headless)
        context = browser.new_context(
            viewport={"width": 1920, "height": 1080},
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        
        # Enable request/response logging if debug mode
        if debug:
            page.on("request", lambda request: print(f">> {request.method} {request.url}") if "search-by-location" in request.url else None)
            page.on("response", lambda response: print(f"<< {response.status} {response.url}") if "search-by-location" in response.url else None)
        
        try:
            # Generate a search ID to use consistently
            search_params['search_id'] = str(uuid.uuid4())[:10]
            
            # Process pages using direct URL navigation
            for page_num in range(1, max_pages + 1):
                start_index = (page_num - 1) * rows_per_page
                
                try:
                    # Navigate to the specific page
                    if not navigate_to_search_results(page, search_params, start_index, rows_per_page):
                        print(f"Failed to navigate to page {page_num}")
                        break
                    
                    # Wait a bit for dynamic content
                    time.sleep(2)
                    
                    # Get page content
                    page_html = page.content()
                    
                    # Save HTML for debugging
                    if save_html:
                        save_page_source(page_html, page_num, search_params)
                    
                    # Extract provider data
                    page_providers = extract_providers_from_html(page_html)
                    
                    if page_providers:
                        all_providers.extend(page_providers)
                        print(f"Extracted {len(page_providers)} providers from page {page_num} (start={start_index})")
                        
                        # If we got fewer results than expected, we might be at the end
                        if len(page_providers) < rows_per_page:
                            print(f"Got {len(page_providers)} results (less than {rows_per_page}), likely reached end")
                            break
                    else:
                        print(f"No providers found on page {page_num}, stopping pagination")
                        break
                    
                    # Rate limiting
                    time.sleep(1)
                    
                except Exception as e:
                    print(f"Error processing page {page_num}: {str(e)}")
                    if debug:
                        page.screenshot(path=f"error_page_{page_num}.png")
                    break
            
        except Exception as e:
            print(f"Error during scraping: {str(e)}")
            if debug:
                page.screenshot(path="error_screenshot.png")
        
        finally:
            browser.close()
    
    return all_providers

def process_and_save_data(providers, search_params, filename_prefix="aged_care_providers"):
    """Process the extracted data and save to CSV and JSON files"""
    if not providers:
        print("No provider data to process")
        return None
    
    # Create DataFrame
    df = pd.DataFrame(providers)
    
    # Clean up data
    if 'room_types' in df.columns:
        df['room_types_str'] = df['room_types'].apply(lambda x: ', '.join(x) if isinstance(x, list) else str(x))
    
    # Create filename with search parameters
    location_safe = "".join(c for c in search_params.get('location', 'unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
    care_type_safe = "".join(c for c in search_params.get('care_type', 'unknown') if c.isalnum() or c in (' ', '-', '_')).rstrip()
    
    filename = f"{filename_prefix}_{location_safe}_{care_type_safe}.csv"
    
    # Save to CSV
    df.to_csv(filename, index=False)
    print(f"Data saved to CSV: {filename}")
    
    # Save as JSON
    json_filename = filename.replace('.csv', '.json')
    df.to_json(json_filename, orient='records', indent=2)
    print(f"Data saved to JSON: {json_filename}")
    
    return df

def main():
    print("Starting the My Aged Care provider scraping process...")
    
    # Define search parameters
    search_params = {
        'location': 'Sydney NSW 2000',
        'care_type': 'agedCareHomes',  # or 'homecare', 'respite', etc.
        'room_type': 'dontMind'  # or 'single', 'shared', etc.
    }
    
    # Scrape the data
    providers = scrape_aged_care_providers(
        search_params=search_params,
        max_pages=50,
        save_html=True,
        debug=True,
        headless=True  # Set to False to see the browser
    )
    
    # Process and save the data
    df = process_and_save_data(providers, search_params)
    
    # Display summary
    print(f"Scraping complete. Collected {len(df) if df is not None else 0} providers in total.")
    
    # Display sample
    if df is not None and not df.empty:
        print("\nSample of scraped data:")
        sample_columns = ['name', 'service_type', 'address', 'phone']
        available_columns = [col for col in sample_columns if col in df.columns]
        print(df[available_columns].head())
        print(f"\nColumns available: {list(df.columns)}")

if __name__ == "__main__":
    main()