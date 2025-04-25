import   logging
logger = logging.getLogger(__name__)
from     config.config import AppConfig 
from     urllib.error import URLError
from     textwrap import dedent
from     utils.helpers import get_sheet_url_from_user
import   pandas as pd
import   sys

template_sheet_url = AppConfig.template_sheet_url
class Sheets:
    @staticmethod
    def read_google_sheet(sheet_url):
        # Extract the base URL from the provided Google Sheet URL
        base_url = sheet_url.split('/edit')[0]
        dataframes = []
        # Define the worksheets and their respective columns to be read
        worksheets = {
            'Agents': ['Agent Role', 'Goal', 'Backstory', 'Tools', 'Allow delegation', 'Verbose', 'Memory', 'Max_iter','Model Name', 'Temperature', 'Function Calling Model'],
            'Tasks' : ['Task Name', 'Agent', 'Instructions', 'Expected Output'],
            'Crew'  : ['Team Name',	'Assignment','Verbose', 'Process', 'Memory', 'Embedding model', 'Manager LLM', 't', 'num_ctx'],
            'Models': ['Model', 'Context size (local only)', 'Provider', 'base_url','Deployment'],
            'Tools' : ['Tool', 'On', 'Class', 'Args',  'Model', 'Embedding Model']
        }
        
        for worksheet, columns in worksheets.items():
            url = f'{base_url}/gviz/tq?tqx=out:csv&sheet={worksheet}'
            # Read the worksheet into a DataFrame, selecting only the specified columns
            try:
                data = pd.read_csv(url, usecols=columns)
                if worksheet == 'Agents': # sanitize the data
                    data.dropna(subset=['Agent Role'], inplace=True)

                    for col in ['Agent Role', 'Goal','Backstory', 'Tools', 'Model Name', 'Function Calling Model']:
                        data[col] = data[col].astype(str).apply(dedent).replace('None', None)

                    for col in ['Tools']:
                        data[col] = data[col].replace('\n','')
                    for col in ['Allow delegation', 'Verbose', 'Memory']:
                        data[col] = data[col].astype(bool)
                    
                    data['Temperature'] = data['Temperature'].astype(float)
                    data['Max_iter'] = data['Max_iter'].astype(int)

                if worksheet == 'Models':
                    data['Context size (local only)'] = data['Context size (local only)'].replace(0, None)
                    data['base_url'] = data['base_url'].replace("None", None)
                    data['Deployment'] = data['Deployment'].replace("None", None)
                if worksheet == 'Tasks':
                    #check if all columns are present are string. If not, print error and exit
                    for col in columns:
                        #convert all columns to string
                        data[col] = data[col].astype(str)
                        if data[col].dtype != 'object':
                            raise ValueError(f"Column '{col}' is not of type 'Plain Text'.")                  
                if worksheet == "Crew":
                    for col in ['Team Name', 'Assignment', 'Process', 'Embedding model', 'Manager LLM']:                    
                        data[col] = data[col].astype(str).apply(dedent).replace('None', None).replace('nan', None)
                    for col in ['Verbose', 'Memory']:
                        data[col] = data[col].astype(bool)
                    data['t'] = data['t'].astype(float)
                    data['num_ctx'] = data['num_ctx'].astype(int).replace(0, None)
                if worksheet == 'Tools':
                    data.replace('None', None, inplace=True)
            except Exception as e:
                return e
    
            data = data.where(pd.notnull(data), None) # Replace NaN values with None

            # Append the DataFrame to the list of dataframes
            dataframes.append(data)

        return dataframes
    
    @staticmethod
    def parse_table(url=template_sheet_url):
        num_att = 0
        while num_att < 10:
            try:
                dataframes = Sheets.read_google_sheet(url)
                if isinstance(dataframes, Exception):
                    raise dataframes
                break
            except ValueError as e:
                logger.error(f"ValueError occurred: {e}")
                print(f"Oops! Something went bonkers with the sheet. {e}")
                url = get_sheet_url_from_user()
                num_att += 1
            except URLError as e:
                logger.error(f"URLError occurred: {e}")
                print(f"Trying to open '{url}' and I'm all thumbs (which is sad because I don't have any)! Can you check that URL for me? {e}")
                url = get_sheet_url_from_user()
                num_att += 1
        else:
            print("10 attempts? Is this a new world record? I'm not equipped for marathons! Gotta hit the shutdown button now.")
            sys.exit(0)

        Agents = dataframes[0]
        Tasks  = dataframes[1]
        Crew   = dataframes[2]
        Models = dataframes[3]
        Tools  = dataframes[4]
        
        return Agents, Tasks, Crew, Models, Tools
       
        # from sqlalchemy import create_engine
        # engine = create_engine('sqlite:///my_database.db')

        # # Write DataFrames to SQL tables
        # Agents.to_sql('Agents', con=engine, index=False, if_exists='replace')
        # Tasks.to_sql('Tasks', con=engine, index=False, if_exists='replace')
        # Crew.to_sql('Crew', con=engine, index=False, if_exists='replace')
        # Models.to_sql('Models', con=engine, index=False, if_exists='replace')
        # Tools.to_sql('Tools', con=engine, index=False, if_exists='replace')