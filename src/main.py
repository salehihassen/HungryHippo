import os
os.environ['USER_AGENT'] = 'MyCustomAgent/1.0' # For Langchain
import bs4
from langchain import hub
from langchain_chroma import Chroma
from langchain_community.document_loaders import WebBaseLoader
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import RunnablePassthrough, RunnableParallel
from langchain_ollama import OllamaEmbeddings, ChatOllama
from langchain_text_splitters import RecursiveCharacterTextSplitter
from langchain.memory import ConversationBufferMemory
from langchain.prompts import ChatPromptTemplate

from utils import extract_sources, setup_web_request_cache, get_current_datetime, EVENT_RAG_PROMPT

LOCAL_FUN_WEB_CSV_PATH = os.path.join(os.pardir, "/data/local_fun_web.csv")
OLLAMA_ADDR = "0.0.0.0:11434"


# Extract local fun events

def format_docs(docs):
    return "\n\n".join(doc.page_content for doc in docs)

class HungryHippo:
    def __init__(self, llm_hosting_address=OLLAMA_ADDR, prompt_template=EVENT_RAG_PROMPT):
        self.llm_hosting_address = llm_hosting_address
        self.prompt_template = prompt_template
        self.vector_store = self.index_setup()
        self.retriever = self.vector_store.as_retriever()
        self.llm = ChatOllama(model="llama3.1", temperature=0, base_url=self.llm_hosting_address)
        self.memory = ConversationBufferMemory(return_messages=True)
        self.create_rag_chain() # stored in self.rag_chain

    def index_setup(self):
        setup_web_request_cache()
        web_sources = extract_sources(LOCAL_FUN_WEB_CSV_PATH, verbose=False)
        loader = WebBaseLoader(
            web_paths=(web_sources),
            # bs_kwargs=dict(parse_only=WEB_FILTER_BY_CLASS),
        )
        docs = loader.load()
        text_splitter = RecursiveCharacterTextSplitter(chunk_size=1000, chunk_overlap=200)
        splits = text_splitter.split_documents(docs)
        vectorstore = Chroma.from_documents(documents=splits, embedding=OllamaEmbeddings(model="nomic-embed-text:latest", base_url=self.llm_hosting_address,))
        return vectorstore
    def create_rag_chain(self):
        self.rag_chain = (
        RunnableParallel(
            context=self.retriever | format_docs,
            question=RunnablePassthrough(),
            date=RunnablePassthrough() | get_current_datetime,
            history=RunnablePassthrough() | (lambda _: self.memory.load_memory_variables({})["history"])
        ) 
        | self.prompt_template.partial()
        | self.llm 
        | StrOutputParser()
        )
    
    def preprocess(self, input_dict):
        # TODO - finish implementing conditional chain so RAG and other tools won't be called if pre-processing deems it unneccessary
        pre_process_prompt = ChatPromptTemplate.from_template(
        "Given the following question and the current date, determine if the question can be answered directly or if it requires additional context retrieval. Respond with either 'DIRECT' or 'RAG'.\n\nQuestion: {question}\nCurrent Date: {date}\n\nDecision:"
        )
        chain = pre_process_prompt | self.llm | StrOutputParser()
        decision = chain.invoke(input_dict)
        return {"need_rag": decision.strip() == "RAG", **input_dict}
    
    def direct_answer(input_dict):
        # TODO - finish implementing conditional chain so RAG and other tools won't be called if pre-processing deems it unneccessary
        pass
    
    def retrieval_and_answer(self, question):
        response = self.rag_chain.invoke(question)
        self.memory.save_context({"input":question},{"output":response})
        return response
    
if __name__ == "__main__":
    print(get_current_datetime())
    hungry_hippo = HungryHippo()
    print("Welcome to HungryHippo! Type 'exit' to end the conversation")
    while True:
        user_input = input("You: ")
        if user_input.lower().strip() == 'exit':
            print("HungryHippo: Goodbye! Have a great day.")
            break
        response = hungry_hippo.retrieval_and_answer(user_input.strip())
        print("HungryHippo:", response)
