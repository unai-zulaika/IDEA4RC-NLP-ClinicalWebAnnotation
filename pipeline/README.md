# IDEA4RC-NLP Ingestion module

This repository presents the IDEA4RC NLP Ingestion module which receives a file with patient texts and produces an output excel file compliant with the IDEA4RC data model that can be feed into the ETL process.

There are two major components in this source code:

* A status web to track the ingestion process
* A REST API to handle the processes and flow of the data. Within the REST API there are also three main services:
    - The NLP service which extracts the relevant concepts related to IDEA4RC from the texts. It contains a dedicated endpoint an loads a LLM to perform the analysis. The extracted information is stored in an excel file and feed to the next service.
    - The linking service tries to integrate the different entities and variables obtained from the NLP service. The main goal is to find the relationships of the data model in the actual data instances. After the links have been filled, the excel fill is fed to the last service.
    - 


Currently the implementation runs after docker-compose. After cloning the repository you can run ```docker-compose up``` and after the command finishes you can access to http://localhost:8501/
\
