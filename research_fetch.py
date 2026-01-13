#!/usr/bin/env python3
"""
ResearchFetch - A Python script to retrieve research publications by author
from Europe PMC API and store them in Supabase.
"""

import argparse
import requests
import json
import sys
import time
import os
import re
from datetime import datetime
from typing import Dict, List, Optional, Tuple


# API Endpoints
EUROPE_PMC_SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
EUROPE_PMC_ARTICLE_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/PMC"

# Rate limiting for API calls (500ms between calls)
_last_api_call = None
API_RATE_LIMIT_MS = 500

# Supabase configuration (can be set via environment variables or command line args)
# Note: For server-side scripts, use the service_role key (not the anon key)
# The service_role key bypasses RLS and is designed for server-side use
# Find it in Supabase Dashboard > Settings > API > Project API keys > service_role
SUPABASE_URL = os.getenv("SUPABASE_URL", "")
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "")


def rate_limit():
    """Ensure API calls are rate limited."""
    global _last_api_call
    
    if _last_api_call is not None:
        elapsed_ms = (time.time() - _last_api_call) * 1000
        if elapsed_ms < API_RATE_LIMIT_MS:
            sleep_time = (API_RATE_LIMIT_MS - elapsed_ms) / 1000
            time.sleep(sleep_time)
    
    _last_api_call = time.time()


def search_by_author(last_name: str, first_initial: str, orcid: Optional[str] = None) -> Optional[Dict]:
    """
    Search for articles by author using Europe PMC API.
    Filters results to only include MEDLINE sourced articles.
    
    Args:
        last_name: Author's last name
        first_initial: Author's first name initial
        orcid: Optional ORCID identifier (if provided, uses ORCID instead of name)
        
    Returns:
        JSON response dictionary or None if request fails
    """
    rate_limit()
    
    # If ORCID is provided, use it for more precise searching
    if orcid:
        # Remove any dashes or spaces from ORCID for query
        orcid_clean = orcid.replace("-", "").replace(" ", "")
        # Format as xxxx-xxxx-xxxx-xxxx if needed
        if len(orcid_clean) == 16:
            orcid_formatted = f"{orcid_clean[0:4]}-{orcid_clean[4:8]}-{orcid_clean[8:12]}-{orcid_clean[12:16]}"
        else:
            orcid_formatted = orcid
        query = f'ORCID:{orcid_formatted} AND SRC:MED'
    else:
        # Filter for MEDLINE articles only using SRC:MED
        query = f'AUTH:"{last_name} {first_initial}" AND SRC:MED'
    
    params = {
        "query": query,
        "resultType": "core",
        "format": "json"
    }
    
    try:
        response = requests.get(EUROPE_PMC_SEARCH_URL, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        return None


def get_article_details(pmcid: str) -> Optional[Dict]:
    """
    Retrieve full article details from Europe PMC using PMCID.
    
    Args:
        pmcid: PubMed Central ID
        
    Returns:
        JSON response dictionary or None if request fails
    """
    rate_limit()
    
    url = f"{EUROPE_PMC_ARTICLE_URL}/{pmcid}"
    params = {
        "format": "json",
        "resultType": "core"
    }
    
    try:
        response = requests.get(url, params=params)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"Error making request: {e}")
        return None


def parse_affiliation(affiliation_str: str) -> Dict[str, Optional[str]]:
    """
    Parse affiliation string to extract institution, city, state, and zip.
    Falls back to storing the whole string if parsing fails.
    
    Args:
        affiliation_str: Raw affiliation string
        
    Returns:
        Dictionary with parsed components or raw string
    """
    if not affiliation_str:
        return {
            "name": None,
            "institution": None,
            "city": None,
            "state": None,
            "zip": None,
            "raw": None
        }
    
    # Try to parse common affiliation formats
    # Format examples:
    # "Department, University, City, State ZIP, Country"
    # "Institution, City, Country"
    # "Department, Institution, City State ZIP"
    
    parsed = {
        "name": affiliation_str,  # Default to full string
        "institution": None,
        "city": None,
        "state": None,
        "zip": None,
        "raw": affiliation_str
    }
    
    # Try to extract ZIP code (5 digits or 5+4 format)
    zip_match = re.search(r'\b(\d{5}(?:-\d{4})?)\b', affiliation_str)
    if zip_match:
        parsed["zip"] = zip_match.group(1)
    
    # Try to extract US state (2-letter abbreviation)
    state_match = re.search(r'\b([A-Z]{2})\b(?=\s+\d{5})', affiliation_str)
    if state_match:
        parsed["state"] = state_match.group(1)
    
    # Split by commas to try to extract components
    parts = [p.strip() for p in affiliation_str.split(',')]
    
    if len(parts) >= 2:
        # Usually institution is in first parts, city in later parts
        # Try to identify city (usually has state/zip after it or is before country)
        for i, part in enumerate(parts):
            # Check if this part looks like a city (has state/zip nearby)
            if i < len(parts) - 1:
                next_part = parts[i + 1]
                # If next part is state or zip, current might be city
                if re.match(r'^[A-Z]{2}$', next_part) or re.match(r'^\d{5}', next_part):
                    parsed["city"] = part
                    # Institution is likely before city
                    if i > 0:
                        parsed["institution"] = parts[i - 1]
                    break
        
        # If we didn't find city, try last non-country part as city
        if not parsed["city"] and len(parts) >= 3:
            # Last part might be country, second-to-last might be city
            parsed["city"] = parts[-2] if not re.match(r'^(USA|United States|UK|United Kingdom)', parts[-1], re.I) else parts[-2]
            parsed["institution"] = parts[0] if len(parts) > 2 else None
    
    # Set name to institution if we found one, otherwise keep full string
    if parsed["institution"]:
        parsed["name"] = parsed["institution"]
    
    return parsed


def get_first_affiliation(result: Dict, first_author: Dict) -> str:
    """
    Extract the first affiliation from result or first author.
    Handles multiple affiliations by picking the first one.
    
    Args:
        result: Result object from API response
        first_author: First author object
        
    Returns:
        Affiliation string or empty string
    """
    # First, try to get affiliation from first author's authorAffiliationDetailsList
    author_affiliations = first_author.get("authorAffiliationDetailsList", {}).get("authorAffiliation", [])
    if author_affiliations and len(author_affiliations) > 0:
        # Get first affiliation from the list
        return author_affiliations[0].get("affiliation", "")
    
    # Fall back to top-level affiliation field
    return result.get("affiliation", "")


def extract_author_info(author_data: Dict) -> Dict[str, Optional[str]]:
    """
    Extract author information from author object.
    
    Args:
        author_data: Author object from API response
        
    Returns:
        Dictionary with author information
    """
    full_name = author_data.get("fullName", "")
    first_name = author_data.get("firstName", "")
    last_name = author_data.get("lastName", "")
    initials = author_data.get("initials", "")
    
    # Extract first initial
    first_initial = None
    if initials:
        first_initial = initials[0] if len(initials) > 0 else None
    elif first_name:
        first_initial = first_name[0].upper()
    elif full_name:
        # Try to extract first initial from full name
        parts = full_name.split()
        if parts:
            first_initial = parts[0][0].upper() if parts[0] else None
    
    # Extract last name if not provided
    if not last_name and full_name:
        parts = full_name.split()
        if parts:
            last_name = parts[-1]
    
    return {
        "full_name": full_name,
        "first_name_initial": first_initial,
        "last_name": last_name
    }


def extract_publication_data_from_search(result: Dict) -> Dict:
    """
    Extract publication data from search result (when inPMC is "N").
    
    Args:
        result: Result object from search response
        
    Returns:
        Dictionary with publication data
    """
    author_list = result.get("authorList", {}).get("author", [])
    
    # Get first author
    first_author = author_list[0] if author_list else {}
    author_info = extract_author_info(first_author)
    
    # Get contributors (all authors after first)
    contributors = []
    if len(author_list) > 1:
        for author in author_list[1:]:
            full_name = author.get("fullName", "")
            if full_name:
                contributors.append(full_name)
    
    # Extract keywords
    keywords = []
    keyword_list = result.get("keywordList", {}).get("keyword", [])
    if keyword_list:
        keywords = [kw for kw in keyword_list if kw]
    
    # Get affiliation (first author's first affiliation)
    affiliation_str = get_first_affiliation(result, first_author)
    affiliation_parsed = parse_affiliation(affiliation_str)
    
    return {
        "pmid": result.get("pmid", ""),
        "pmcid": result.get("pmcid"),
        "title": result.get("title", ""),
        "abstract": result.get("abstractText", ""),
        "author": author_info,
        "contributors": contributors,
        "keywords": keywords,
        "affiliation": affiliation_parsed,
        "is_open_access": result.get("isOpenAccess", False),
        "publication_date": result.get("firstPublicationDate"),
        "grant_agency": None,  # Not available in search results
        "license": None  # Not available in search results
    }


def extract_publication_data_from_detail(result: Dict) -> Dict:
    """
    Extract publication data from article detail response (when inPMC is "Y").
    
    Args:
        result: Result object from article detail response
        
    Returns:
        Dictionary with publication data
    """
    author_list = result.get("authorList", {}).get("author", [])
    
    # Get first author
    first_author = author_list[0] if author_list else {}
    author_info = extract_author_info(first_author)
    
    # Get contributors (all authors after first)
    contributors = []
    if len(author_list) > 1:
        for author in author_list[1:]:
            full_name = author.get("fullName", "")
            if full_name:
                contributors.append(full_name)
    
    # Extract keywords
    keywords = []
    keyword_list = result.get("keywordList", {}).get("keyword", [])
    if keyword_list:
        keywords = [kw for kw in keyword_list if kw]
    
    # Get affiliation (first author's first affiliation)
    affiliation_str = get_first_affiliation(result, first_author)
    affiliation_parsed = parse_affiliation(affiliation_str)
    
    # Extract grant agency (first grant's agency)
    grant_agency = None
    grants_list = result.get("grantsList", {}).get("grant", [])
    if grants_list and len(grants_list) > 0:
        grant_agency = grants_list[0].get("agency")
    
    return {
        "pmid": result.get("pmid", ""),
        "pmcid": result.get("pmcid", ""),
        "title": result.get("title", ""),
        "abstract": result.get("abstractText", ""),
        "author": author_info,
        "contributors": contributors,
        "keywords": keywords,
        "affiliation": affiliation_parsed,
        "is_open_access": result.get("isOpenAccess", False),
        "publication_date": result.get("firstPublicationDate"),
        "grant_agency": grant_agency,
        "license": result.get("license")
    }


def find_or_create_author(author_info: Dict, supabase_url: str, supabase_key: str) -> Optional[int]:
    """
    Find or create an author in Supabase.
    Looks up by full_name OR (last_name + first_name_initial).
    
    Args:
        author_info: Dictionary with author information
        supabase_url: Supabase project URL
        supabase_key: Supabase API key
        
    Returns:
        Author ID or None if failed
    """
    if not supabase_url or not supabase_key:
        return None
    
    url = f"{supabase_url}/rest/v1/authors"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    # Try to find existing author
    # First by full_name
    if author_info.get("full_name"):
        check_url = f"{url}?full_name=eq.{author_info['full_name']}"
        try:
            response = requests.get(check_url, headers=headers)
            response.raise_for_status()
            existing = response.json()
            if existing:
                return existing[0]["id"]
        except requests.exceptions.RequestException:
            pass
    
    # Then by last_name + first_name_initial
    if author_info.get("last_name") and author_info.get("first_name_initial"):
        check_url = f"{url}?last_name=eq.{author_info['last_name']}&first_name_initial=eq.{author_info['first_name_initial']}"
        try:
            response = requests.get(check_url, headers=headers)
            response.raise_for_status()
            existing = response.json()
            if existing:
                return existing[0]["id"]
        except requests.exceptions.RequestException:
            pass
    
    # Create new author
    data = {}
    if author_info.get("full_name"):
        data["full_name"] = author_info["full_name"]
    if author_info.get("last_name"):
        data["last_name"] = author_info["last_name"]
    if author_info.get("first_name_initial"):
        data["first_name_initial"] = author_info["first_name_initial"]
    
    if not data.get("full_name"):
        # If no full_name, construct it
        if data.get("last_name") and data.get("first_name_initial"):
            data["full_name"] = f"{data['first_name_initial']}. {data['last_name']}"
        elif data.get("last_name"):
            data["full_name"] = data["last_name"]
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        created = response.json()
        if created:
            return created[0]["id"]
    except requests.exceptions.RequestException as e:
        print(f"Error creating author: {e}")
        return None
    
    return None


def find_or_create_research_center(affiliation_data: Dict, supabase_url: str, supabase_key: str) -> Optional[int]:
    """
    Find or create a research center in Supabase.
    Looks up by name + city.
    
    Args:
        affiliation_data: Dictionary with parsed affiliation data
        supabase_url: Supabase project URL
        supabase_key: Supabase API key
        
    Returns:
        Research center ID or None if failed
    """
    if not supabase_url or not supabase_key:
        return None
    
    if not affiliation_data.get("name"):
        return None
    
    url = f"{supabase_url}/rest/v1/research_centers"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    # Try to find existing research center by name + city
    name = affiliation_data["name"]
    city = affiliation_data.get("city")
    
    if city:
        check_url = f"{url}?name=eq.{name}&city=eq.{city}"
    else:
        check_url = f"{url}?name=eq.{name}"
    
    try:
        response = requests.get(check_url, headers=headers)
        response.raise_for_status()
        existing = response.json()
        if existing:
            return existing[0]["id"]
    except requests.exceptions.RequestException:
        pass
    
    # Create new research center
    data = {
        "name": name,
        "institution": affiliation_data.get("institution"),
        "city": affiliation_data.get("city"),
        "state": affiliation_data.get("state"),
        "zip": affiliation_data.get("zip")
    }
    
    try:
        response = requests.post(url, headers=headers, json=data)
        response.raise_for_status()
        created = response.json()
        if created:
            return created[0]["id"]
    except requests.exceptions.RequestException as e:
        print(f"Error creating research center: {e}")
        return None
    
    return None


def save_publication(publication_data: Dict, author_id: Optional[int], research_center_id: Optional[int],
                    supabase_url: str, supabase_key: str) -> bool:
    """
    Save or update a publication in Supabase.
    
    Args:
        publication_data: Dictionary with publication data
        author_id: Author ID (foreign key)
        research_center_id: Research center ID (foreign key)
        supabase_url: Supabase project URL
        supabase_key: Supabase API key
        
    Returns:
        True if successful, False otherwise
    """
    if not supabase_url or not supabase_key:
        print("Error: Supabase URL and API key must be configured")
        return False
    
    url = f"{supabase_url}/rest/v1/publications"
    headers = {
        "apikey": supabase_key,
        "Authorization": f"Bearer {supabase_key}",
        "Content-Type": "application/json",
        "Prefer": "return=representation"
    }
    
    # Check if publication already exists (by title and author)
    check_url = f"{url}?title=eq.{publication_data['title']}"
    if author_id:
        check_url += f"&author=eq.{author_id}"
    
    try:
        response = requests.get(check_url, headers=headers)
        response.raise_for_status()
        existing = response.json()
        
        # Prepare data for insert/update
        data = {
            "title": publication_data.get("title", ""),
            "pubmed_id": publication_data.get("pmid"),
            "pubmed_central_id": publication_data.get("pmcid"),
            "abstract": publication_data.get("abstract"),
            "publication_date": publication_data.get("publication_date"),
            "is_open_access": publication_data.get("is_open_access"),
            "grant_agency": publication_data.get("grant_agency")
        }
        
        # Add relationships
        if author_id:
            data["author"] = author_id
        if research_center_id:
            data["research_center"] = research_center_id
        
        # Add JSON fields
        if publication_data.get("contributors"):
            data["contributors"] = publication_data["contributors"]
        if publication_data.get("keywords"):
            data["keywords"] = publication_data["keywords"]
        
        if existing:
            # Update existing record
            record_id = existing[0]["id"]
            update_url = f"{url}?id=eq.{record_id}"
            # Only update fields that are missing/null
            update_data = {k: v for k, v in data.items() if v is not None}
            response = requests.patch(update_url, headers=headers, json=update_data)
            response.raise_for_status()
            return True
        else:
            # Insert new record
            response = requests.post(url, headers=headers, json=data)
            response.raise_for_status()
            return True
            
    except requests.exceptions.RequestException as e:
        print(f"Error saving publication: {e}")
        if hasattr(e, 'response') and e.response is not None:
            print(f"Response: {e.response.text}")
        return False


def get_user_input(prompt: str) -> str:
    """
    Get user input with Y/N prompt.
    
    Args:
        prompt: Prompt message to display
        
    Returns:
        User's response (Y or N)
    """
    while True:
        response = input(prompt).strip().upper()
        if response in ['Y', 'N']:
            return response
        print("Please enter Y or N")


def get_optional_text_input(prompt: str) -> Optional[str]:
    """
    Get optional text input from user.
    
    Args:
        prompt: Prompt message to display
        
    Returns:
        User's input string (may be empty) or None
    """
    response = input(prompt).strip()
    return response if response else None


def main():
    parser = argparse.ArgumentParser(
        description="Retrieve research publications by author from Europe PMC API"
    )
    parser.add_argument(
        "last_name",
        type=str,
        help="Author's last name"
    )
    parser.add_argument(
        "first_initial",
        type=str,
        help="Author's first name initial"
    )
    parser.add_argument(
        "--orcid",
        type=str,
        default=None,
        help="Optional ORCID identifier (e.g., 0000-0001-7292-8084). If provided, searches by ORCID instead of name."
    )
    
    args = parser.parse_args()
    
    # Get Supabase configuration from environment variables
    supabase_url = SUPABASE_URL
    supabase_key = SUPABASE_KEY
    
    # Step 1: Search by author
    if args.orcid:
        print(f"\nSearching by ORCID: {args.orcid}...")
    else:
        print(f"\nSearching for author: {args.last_name} {args.first_initial}...")
    search_result = search_by_author(args.last_name, args.first_initial, args.orcid)
    
    if not search_result:
        print("Error: Failed to retrieve results from API")
        sys.exit(1)
    
    # Step 2: Check results and prompt user
    hit_count = search_result.get("hitCount", 0)
    results = search_result.get("resultList", {}).get("result", [])
    
    if hit_count == 0 or not results:
        print("no results found for that Author combination")
        sys.exit(0)
    
    print(f"{hit_count} found. Would you like me to retrieve publication details found associated with this author Y/N?")
    
    user_response = get_user_input("Enter Y or N: ")
    
    if user_response != 'Y':
        print("Exiting...")
        sys.exit(0)
    
    # Ask about title filtering
    title_filter = get_optional_text_input("\nWould you like to only save publications with a specific word or phrase in the title? (Enter word/phrase or press Enter to skip): ")
    
    # Step 3: Process each result
    print(f"\nProcessing {len(results)} publications...\n")
    
    all_publications = []
    
    for i, result in enumerate(results, 1):
        pmid = result.get("pmid", "N/A")
        pmcid = result.get("pmcid", "")
        title = result.get("title", "N/A")
        
        print(f"Processing publication {i}/{len(results)} (PMId: {pmid})...")
        if title != "N/A":
            print(f"  Title: {title[:100]}..." if len(title) > 100 else f"  Title: {title}")
        
        # Check if article has PMC entry
        in_pmc = result.get("inPMC", "N")
        
        if in_pmc == "Y" and pmcid:
            # Fetch full article details
            article_detail = get_article_details(pmcid)
            if article_detail and article_detail.get("result"):
                pub_data = extract_publication_data_from_detail(article_detail["result"])
                all_publications.append(pub_data)
            else:
                print(f"  Warning: Failed to retrieve details for PMCID {pmcid}, using search result data")
                pub_data = extract_publication_data_from_search(result)
                all_publications.append(pub_data)
        else:
            # Extract from search result
            pub_data = extract_publication_data_from_search(result)
            all_publications.append(pub_data)
    
    # Filter by title if a filter was provided
    if title_filter:
        original_count = len(all_publications)
        all_publications = [
            pub for pub in all_publications 
            if title_filter.lower() in pub.get('title', '').lower()
        ]
        filtered_count = len(all_publications)
        print(f"\nFiltered publications: {filtered_count} out of {original_count} match the title filter '{title_filter}'.")
    
    print(f"\nCompleted! Retrieved details for {len(all_publications)} publications.")
    
    # Step 4: Save to Supabase if configured
    if supabase_url and supabase_key:
        print(f"\nSaving {len(all_publications)} publications to Supabase...")
        saved_count = 0
        failed_count = 0
        
        for i, pub_data in enumerate(all_publications, 1):
            print(f"\nProcessing publication {i}/{len(all_publications)} (PMId: {pub_data.get('pmid', 'N/A')})...")
            
            # Find or create author
            author_id = find_or_create_author(pub_data.get("author", {}), supabase_url, supabase_key)
            if author_id:
                print(f"  Author ID: {author_id}")
            else:
                print(f"  Warning: Failed to find/create author")
            
            # Find or create research center
            research_center_id = None
            if pub_data.get("affiliation", {}).get("name"):
                research_center_id = find_or_create_research_center(
                    pub_data.get("affiliation", {}), 
                    supabase_url, 
                    supabase_key
                )
                if research_center_id:
                    print(f"  Research Center ID: {research_center_id}")
            
            # Save publication
            if save_publication(pub_data, author_id, research_center_id, supabase_url, supabase_key):
                saved_count += 1
                print(f"  ✓ Saved successfully")
            else:
                failed_count += 1
                print(f"  ✗ Failed to save")
        
        print(f"\nSupabase save complete: {saved_count} saved, {failed_count} failed.")
    else:
        print("\nNote: Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY environment variables to enable saving.")


if __name__ == "__main__":
    main()
