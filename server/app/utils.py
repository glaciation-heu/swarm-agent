import re

def get_keyword_from_query(query):
    
    matches = re.findall(r'\{(.*?)\}', query)
    # query_string = [line for line in query.split("\n") if ("?" in line and "SELECT" not in line)][0]
    
    print("matches =", matches)
    
    query_string = [elem for elem in matches[0].split(" ") if len(elem)>1]
    
    print("query_string =" ,query_string)
    q_sub, q_pre, q_obj = query_string[0:3]
        
    keyword = ""
    if "?" not in q_pre:
        keyword += q_pre.split(":")[1]
    if "?" not in q_obj:
        keyword += '_'+q_obj.split("^^")[0].replace('"','')
        
    
    return keyword


# PREFIX ns1: <http://dellemc.com:8080/icv/>
# PREFIX schema: <https://schema.org/>
# PREFIX rdf: <http://www.w3.org/1999/02/22-rdf-syntax-ns#>

# SELECT *
# WHERE {
#   ?vehicle ns1:vin ?vin .
# }
