# Summary
This python application makes requests to the Europe PMC API.  This application will be used to retrieve publications by author (lastname first initial), and then retrieve the details of each individual publication by that author.  It will then post the publication details to a Supabase API for storage in a Supabase database.


### Updated Sequence
1. Use ESearch on PMC to find articles by author → get PMC IDs
2. Use Europe PMC to fetch full text + metadata
3. Parse the XML/JSON to extract what you need
4. Store references to original PMC IDs for citation


### Sequence
1. User excecutes this python script and passes it the auther's last name and first name initial.  This python script then makes a search for the author using this endpoint:
- *Search by Author - First: using Europe Search endpoint, if no results found, search using NIH Eutils Sarch*
- Europe Search Endpoint:
- https://www.ebi.ac.uk/europepmc/webservices/rest/search?query=AUTH:"{LastName FirstInitial}"&resultType=core&format=json


2. The python script returns a message to the user.  If there are no results, the message is `"no results found for that Author combinanametion"`.  If there are results returned, the messsage is `[number of results] found. Would you like me to retrieve publication details found associated with this author Y/N?`

3. If the enters `Y`,  the findPublicationDetail script will iterate through the make a request to the `bioc-pubmed-url` below, passing the pmid as a path value in the URL.  The python script will iterate through the documents array in the JSON results and retrieve id, title, abstract.  
- If you're iterating through through Europe Search Endpoint Results, do this;
    a. Iterate through resultList.result array
    b. Determine if this article has a PMC entry by looking at the "inPMC" value.  
        i. If the inPMC value is "Y" 
            aa. Retrieve the article details using the Europe Search Endpoint:  https://www.ebi.ac.uk/europepmc/webservices/rest/PMC/{PMCID}?format=json&resultType=core
            bb. Extract the following values: pmid, pmcid, title, author (first value of authorList.author), contributors (all entries in authorlist.author after the first value), pubYear, abstractText, affiliation,grant.agency,keywordList.keyword[], isOpenAccess, License, firstPublicationDate.
        ii.  If the inPMC value is "N".  Extract the following values from the author-search result object:
            aa. pmid, title, author (fullName from the first value in the authorlist.author array), contributors (fullName from all authorList.author values after the first value in the array), affiliation, abstractText, keywordList.keyword[], isOpenAccess, firstPublicationDate
4. Store the publication in the Supabase publications, author, and research_center tables:
- a. Look up the author in the authors table, querying for the last name and first initial in the extracted author data. If the author record *does not* exist, create a record in the authors table and then retrieve the id value for that author value. If the author record *does* exist, retrieve the id value assocated with that author record
- b. Look the research_center record, querying for the name and location values in the affiiiation data. If the research_center record *does not* exist, create a record in the research_center table and then retrieve the id value for that value. If the research_center record *does* exist, retrieve the id value assocated with that record
- c. Look up the publication in the publications table, querying the title and author.  If the publication record *does not* exist, create a record in the publications table using extracted data and including the authorId and reserch_centerId If the research_center record *does* exist, update any fields that are missing with extracted data.
    

## Schemas
1. json-schemas/europe-pmc-search.json 
2. json-schemas/europe-pmc-article-detail.json


#### Appendix
Not used:  - NIH EUtils Search
- https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pmc&term={LastName FirstInitial}[Author]&retmode=JSON&retmax=300
