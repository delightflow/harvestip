import os
from dotenv import load_dotenv
load_dotenv()
import streamlit as st
import time
import base64
import uuid
import tempfile
from langchain_upstage import UpstageEmbeddings
from langchain_community.vectorstores import Chroma
from langchain_community.document_loaders import PyPDFLoader
from openai import OpenAI

if "id" not in st.session_state:
    st.session_state.id = uuid.uuid4()
    st.session_state.file_cache = {}

session_id = st.session_state.id
client = None

def reset_chat():
    st.session_state.messages = []
    st.session_state.context = None


def display_pdf(file):
    # Opening file from file path

    st.markdown("### 선행문헌 미리보기")
    base64_pdf = base64.b64encode(file.read()).decode("utf-8")

    # Embedding PDF in HTML
    pdf_display = f"""<iframe src="data:application/pdf;base64,{base64_pdf}" width="400" height="100%" type="application/pdf"
                        style="height:100vh; width:100%"
                    >
                    </iframe>"""

    # Displaying File
    st.markdown(pdf_display, unsafe_allow_html=True)


with st.sidebar:

    st.header(f"선행문헌을 등록하세요!")
    
    uploaded_file = st.file_uploader("PDF 파일만 가능 `.pdf` file", type="pdf")

    if uploaded_file:
        print(uploaded_file)
        try:
            file_key = f"{session_id}-{uploaded_file.name}"

            with tempfile.TemporaryDirectory() as temp_dir:
                file_path = os.path.join(temp_dir, uploaded_file.name)
                print("file path:", file_path)
                
                with open(file_path, "wb") as f:
                    f.write(uploaded_file.getvalue())
                
                file_key = f"{session_id}-{uploaded_file.name}"
                st.write("문헌을 인덱싱하고 있습니다...")

                if file_key not in st.session_state.get('file_cache', {}):

                    if os.path.exists(temp_dir):
                            print("temp_dir:", temp_dir)
                            loader = PyPDFLoader(
                                file_path
                            )
                    else:    
                        st.error('파일을 확인할 수 없습니다. 다시 확인해주세요...')
                        st.stop()
                    
                    pages = loader.load_and_split()

                    vectorstore = Chroma.from_documents(pages, UpstageEmbeddings(model="solar-embedding-1-large"))

                    retriever = vectorstore.as_retriever(k=2)

                    from langchain_upstage import ChatUpstage
                    from langchain_core.messages import HumanMessage, SystemMessage

                    # chat = ChatUpstage(upstage_api_key=st.secrets["UPSTAGE_API_KEY"])
                    chat = ChatUpstage(upstage_api_key=os.getenv("UPSTAGE_API_KEY"))

                    # 1) 챗봇에 '기억'을 입히기 위한 첫번째 단계 

                    # 이전의 메시지들과 최신 사용자 질문을 분석해, 문맥에 대한 정보가 없이 혼자서만 봤을때 이해할 수 있도록 질문을 다시 구성함
                    # 즉 새로 들어온 그 질문 자체에만 집중할 수 있도록 다시 재편성
                    from langchain.chains import create_history_aware_retriever
                    from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder

                    contextualize_q_system_prompt = """입력된 선행기술 특허 문헌을 기반으로 
                    사용자의 아이디어와 결합하여 발명설명서(invention discloser)를 생성합니다. 
                    발명설명서는 전문 특허명세서 형식입니다. 
                    이전 대화 내용과 최신 사용자 질문이 있을 때, 이 질문이 이전 대화 내용과 관련이 있을 수 있습니다. 
                    이런 경우, 대화 내용을 알 필요 없이 독립적으로 이해할 수 있는 질문으로 바꾸세요. 
                    질문에 답할 필요는 없고, 필요하다면 그저 다시 구성하거나 그대로 두세요."""

                    # MessagesPlaceholder: 'chat_history' 입력 키를 사용하여 이전 메세지 기록들을 프롬프트에 포함시킴.
                    # 즉 프롬프트, 메세지 기록 (문맥 정보), 사용자의 질문으로 프롬프트가 구성됨. 
                    contextualize_q_prompt = ChatPromptTemplate.from_messages(
                        [
                            ("system", contextualize_q_system_prompt),
                            MessagesPlaceholder("chat_history"),
                            ("human", "{input}"),
                        ]
                    )

                    # 이를 토대로 메세지 기록을 기억하는 retriever를 생성합니다.
                    history_aware_retriever = create_history_aware_retriever(
                        chat, retriever, contextualize_q_prompt
                    )

                    # 2) 두번째 단계로, 방금 전 생성한 체인을 사용하여 문서를 불러올 수 있는 retriever 체인을 생성합니다.
                    from langchain.chains import create_retrieval_chain
                    from langchain.chains.combine_documents import create_stuff_documents_chain

                    qa_system_prompt = """발명, 특허출원 업무를 돕는 보조원입니다. 
                    발명설명서 생성 요청에 답하기 위해 검색된 내용을 사용하세요. 
                    답변은 특허명세서 형태로 답변해야합니다.

                    ## 답변 예시
                    📍답변 내용: 
                    📍증거: 

                    {context}"""
                    qa_prompt = ChatPromptTemplate.from_messages(
                        [
                            ("system", qa_system_prompt),
                            MessagesPlaceholder("chat_history"),
                            ("human", "{input}"),
                        ]
                    )

                    question_answer_chain = create_stuff_documents_chain(chat, qa_prompt)

                    # 결과값은 input, chat_history, context, answer 포함함.
                    rag_chain = create_retrieval_chain(history_aware_retriever, question_answer_chain)

                st.success("대화 준비 완료!")
                display_pdf(uploaded_file)
        except Exception as e:
            st.error(f"An error occurred: {e}")
            st.stop()     

# 웹사이트 제목
st.title("HavIP AI 발명명세서 생성기")
st.write("HavIP은 선행문헌을 기반으로 사용자의 아이디어와 결합하여 발명명세서를 생성합니다.")
st.write("발명설명서는 전문 특허명세서 형식입니다.")
st.write("검색증강생성기술을 활용하여 chatGPT보다 더 정확하고 전문적인 발명명세서를 작성합니다.")

if "openai_model" not in st.session_state:
    st.session_state["openai_model"] = "gpt-3.5-turbo"

if "messages" not in st.session_state:
    st.session_state.messages = []

# 대화 내용을 기록하기 위해 셋업
# Streamlit 특성상 활성화하지 않으면 내용이 다 날아감.
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])
        
# 프롬프트 비용이 너무 많이 소요되는 것을 방지하기 위해
MAX_MESSAGES_BEFORE_DELETION = 4

# 웹사이트에서 유저의 인풋을 받고 위에서 만든 AI 에이전트 실행시켜서 답변 받기
if prompt := st.chat_input("선행문헌을 등록하고 아이디어를 입력하면 명세서 형식의 발명명세서를 만들어드려요!"):
    
    
# 유저가 보낸 질문이면 유저 아이콘과 질문 보여주기
     # 만약 현재 저장된 대화 내용 기록이 4개보다 많으면 자르기
    # if len(st.session_state.messages) >= MAX_MESSAGES_BEFORE_DELETION:
    #     # Remove the first two messages
    #     del st.session_state.messages[0]
    #     del st.session_state.messages[0]  
   
    st.session_state.messages.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

# AI가 보낸 답변이면 AI 아이콘이랑 LLM 실행시켜서 답변 받고 스트리밍해서 보여주기
    with st.chat_message("assistant"):
        message_placeholder = st.empty()
        full_response = ""
        
        try:
            result = rag_chain.invoke({"input": prompt, "chat_history": st.session_state.messages})
        except Exception as e:
            st.error(f"선행문헌을 등록해주세요!")
            st.stop()

        # result = rag_chain.invoke({"input": prompt, "chat_history": st.session_state.messages})

        # 증거자료 보여주기
        with st.expander("Evidence context"):
            st.write(result["context"])

        for chunk in result["answer"].split(" "):
            full_response += chunk + " "
            time.sleep(0.2)
            message_placeholder.markdown(full_response + "▌")
            message_placeholder.markdown(full_response)
            
    st.session_state.messages.append({"role": "assistant", "content": full_response})

    new_session_state_messages = []

     # 만약 현재 저장된 대화 내용 기록이 MAX_MESSAGES_BEFORE_DELETION보다 많으면 자르기
    if len(st.session_state.messages) <= MAX_MESSAGES_BEFORE_DELETION:
        new_session_state_messages = st.session_state.messages
    elif len(st.session_state.messages) > MAX_MESSAGES_BEFORE_DELETION:
        # Keep only the last two messages
        new_session_state_messages = st.session_state.messages[-MAX_MESSAGES_BEFORE_DELETION:]

    client = OpenAI(
        api_key=os.getenv("UPSTAGE_API_KEY"),
        base_url="https://api.upstage.ai/v1/solar"
    )
        
    response = client.chat.completions.create(
            model="solar-1-mini-groundedness-check",
            messages=new_session_state_messages
    )

    print(response.choices[0].message.content)
    if response.choices[0].message.content == "grounded":
        st.caption('하빕이 생성한 답변은 검증을 통과했습니다.')
    else:
        st.caption('생성한 답변은 검증을 통과하지 못하였습니다. 신빙성에 유의하세요.')


print("_______________________")
print(st.session_state.messages)
