# Summary
This python application makes requests to the Europe PMC API.  This application will be used to retrieve publications by author (lastname first initial), and then retrieve the details of each individual publication by that author.  It will then post the publication details to a Supabase API for storage in a Supabase database.

## Installation

1. Ensure you have Python 3 installed on your system
2. Install required dependencies:
   ```bash
   pip install -r requirements.txt
   ```

## Configuration

Before running the script, you need to configure your Supabase credentials (optional, but required if you want to save publications to the database):

Set the following environment variables:
- `SUPABASE_URL`: Your Supabase project URL (e.g., `https://your-project.supabase.co`)
- `SUPABASE_KEY`: Your Supabase service_role API key (found in Supabase Dashboard > Settings > API > Project API keys > service_role)

**Note:** Use the `service_role` key (not the `anon` key) as it bypasses Row Level Security and is designed for server-side scripts.

Example (bash/zsh):
```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-service-role-key-here"
```

Example (Windows PowerShell):
```powershell
$env:SUPABASE_URL="https://your-project.supabase.co"
$env:SUPABASE_KEY="your-service-role-key-here"
```

## Usage

### Basic Syntax

```bash
python research_fetch.py <last_name> <first_initial> [--orcid ORCID_ID]
```

### Required Arguments

- `last_name`: Author's last name (required)
- `first_initial`: Author's first name initial (required)

### Optional Flags

- `--orcid`: Optional ORCID identifier (e.g., `0000-0001-7292-8084`). If provided, the script will search by ORCID instead of name, which provides more precise results.

### Examples

**Search by name:**
```bash
python research_fetch.py Smith J
```

**Search by ORCID:**
```bash
python research_fetch.py Smith J --orcid 0000-0001-7292-8084
```

**With environment variables set:**
```bash
export SUPABASE_URL="https://your-project.supabase.co"
export SUPABASE_KEY="your-service-role-key"
python research_fetch.py Doe A
```

## Execution Flow and Follow-up Options

When you run the script, it follows this interactive flow:

### Step 1: Search Execution
The script searches Europe PMC for publications matching your criteria:
- If searching by name: Uses `AUTH:"LastName FirstInitial" AND SRC:MED` query (filters for MEDLINE articles only)
- If searching by ORCID: Uses `ORCID:xxxx-xxxx-xxxx-xxxx AND SRC:MED` query

### Step 2: Results Display
After the search completes, you'll see one of two messages:
- **No results found:** `"no results found for that Author combination"` - The script exits
- **Results found:** `"[number] found. Would you like me to retrieve publication details found associated with this author Y/N?"`

### Step 3: Publication Retrieval Prompt
If results are found, you'll be prompted:
```
Enter Y or N:
```

**Options:**
- **Y**: Proceed to retrieve and process publication details
- **N**: Exit the script without retrieving details

**Note:** The script will only accept `Y` or `N` (case-insensitive). Any other input will prompt you to try again.

### Step 4: Title Filtering (Optional)
If you entered `Y` in Step 3, you'll be prompted:
```
Would you like to only save publications with a specific word or phrase in the title? (Enter word/phrase or press Enter to skip):
```

**Options:**
- **Enter a word/phrase**: Only publications containing that text (case-insensitive) in the title will be processed and saved
- **Press Enter (empty)**: Process all publications without filtering

**Example:** If you enter `"cancer"`, only publications with "cancer" in the title will be saved.

### Step 5: Processing and Saving
The script will:
1. Process each publication (retrieving full details if available)
2. Display progress for each publication
3. If Supabase is configured, save publications to the database:
   - Creates or finds authors in the `authors` table
   - Creates or finds research centers in the `research_centers` table
   - Creates or updates publications in the `publications` table
4. Display a summary of saved/failed publications

**Note:** If Supabase credentials are not configured, the script will retrieve publication details but display: `"Note: Supabase not configured. Set SUPABASE_URL and SUPABASE_KEY environment variables to enable saving."`


### Updated Sequence
1. Use Europe PMC to find articles by author → get PMC IDs
2. If an article in the results has an PMCID, Use Europe PMC to fetch full text + metadata
3. If an article does not have an PMCID value, extract the metadata provided in the author search
4. Store the extracted data in the publications, authors, and research_centers tables, respectively


### Sequence
1. User excecutes this python script and passes it the auther's last name and first name initial.  This python script then makes a search for the author using this endpoint:
- *Search by Author - First: using Europe Search endpoint, if no results found, search using NIH Eutils Sarch*
- Europe Search Endpoint:
- https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=AUTH:"{LastName FirstInitial}"&resultType=core&format=json


2. The python script returns a message to the user.  If there are no results, the message is `"no results found for that Author combination"`.  If there are results returned, the messsage is `[number of results] found. Would you like me to retrieve publication details found associated with this author Y/N?`

3. If the enters `Y`,  the findPublicationDetail script will iterate through the Europe Search Endpoint Results, as follows;
    a. Iterate through resultList.result array
    b. Determine if this article has a PMC entry by looking at the "inPMC" value.  
        i. If the inPMC value is "Y" 
            aa. Retrieve the article details using the Europe PMC Detail Endpoint:  https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/{PMCID}?format=json&resultType=core
            bb. Extract the following values: pmid, pmcid, title, author (first value of authorList.author), contributors (all entries in authorlist.author after the first value), abstractText, affiliation,grant.agency,keywordList.keyword[], isOpenAccess, license, firstPublicationDate.
        ii.  If the inPMC value is "N".  Extract the following values from the author-search result object:
            aa. pmid, title, author (fullName from the first value in the authorlist.author array), contributors (fullName from all authorList.author values after the first value in the array), affiliation, abstractText, keywordList.keyword[], isOpenAccess, firstPublicationDate
4. Store the publication in the Supabase publications, author, and research_center tables:
- a. Look up the author in the authors table, querying for the last name and first initial in the extracted author data. If the author record *does not* exist, create a record in the authors table and then retrieve the id value for that author value. If the author record *does* exist, retrieve the id value assocated with that author record
- b. Look the research_center record, querying for the name and location values in the affiiation data. If the research_center record *does not* exist, create a record in the research_center table and then retrieve the id value for that value. If the research_center record *does* exist, retrieve the id value assocated with that record
- c. Look up the publication in the publications table, querying the title and author.  If the publication record *does not* exist, create a record in the publications table using extracted data and including the authorId and research_centerId If the research_center record *does* exist, update any fields that are missing with extracted data.
    

## Schemas
1. json-schemas/europe-pmc-search.json 
2. json-schemas/europe-pmc-article-detail.json


#### Appendix
Not used:  - NIH EUtils Search
- https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pmc&term={LastName FirstInitial}[Author]&retmode=JSON&retmax=300
