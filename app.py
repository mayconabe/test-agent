import os
import time
import requests
import streamlit as st
from dotenv import load_dotenv

load_dotenv()

# =========================
# CONFIGURAÇÕES BÁSICAS
# =========================

API_BASE_URL = os.getenv('API_BASE_URL', 'http://163.176.236.162')  # ajuste se necessário
CHAT_ENDPOINT = f'{API_BASE_URL}/chat'

# Você pode definir isso via .env ou direto aqui
DEFAULT_API_KEY = os.getenv('API_KEY')
DEFAULT_USER_ID = os.getenv('USER_ID')
DEFAULT_OPERADORA = os.getenv('OPERADORA')
# =========================
# Página
# =========================
st.set_page_config(
    page_title='Agente Híbrido SQL',
    page_icon='🚀',
    layout='wide'
)
st.title('Saw Chat')

# =========================
# Sidebar — Configuração
# =========================
st.sidebar.header('Configuração da Sessão')

api_key = st.sidebar.text_input('X-API-Key', value=DEFAULT_API_KEY, type='password')
user_id = st.sidebar.text_input('X-User-Id', value=DEFAULT_USER_ID)
operadora = st.sidebar.text_input('X-Operadora', value=DEFAULT_OPERADORA)
api_base_url = st.sidebar.text_input('API Base URL', value=API_BASE_URL)

st.sidebar.markdown('---')
st.sidebar.markdown('Headers enviados para a API:')

st.sidebar.code(
    f"X-API-Key: {api_key or '...'}\n"
    f"X-User-Id: {user_id}\n"
    f"X-Operadora: {operadora}",
    language='bash'
)

if not api_key:
    st.warning('⚠ Defina a X-API-Key na barra lateral para usar o agente.')

# Atualiza o endpoint caso o usuário mude a URL
CHAT_ENDPOINT = f'{api_base_url.rstrip("/")}/chat'

# =========================
# Estado de conversa
# =========================

# Histórico: lista de mensagens {role: 'user'/'assistant', content: str}
st.session_state.setdefault('history', [])

# Última SQL usada
st.session_state.setdefault('last_sql', None)

# Controle de UI (inspirado no app original)
st.session_state.setdefault('show_suggestions', True)
st.session_state.setdefault('is_processing', False)
st.session_state.setdefault('pending_prompt', None)

# Atualiza flag de sugestões: se já houve user, não mostra mais
if any(m.get('role') == 'user' for m in st.session_state['history']):
    st.session_state.show_suggestions = False

# =========================
# Input SEMPRE visível (desabilita durante processamento)
# =========================
user_typed = st.chat_input(
    'Qual sua pergunta sobre os dados?',
    key='chat_box',
    disabled=st.session_state.is_processing or not api_key
)

if user_typed and not st.session_state.is_processing and api_key:
    st.session_state.pending_prompt = user_typed
    st.session_state.show_suggestions = False
    st.session_state.is_processing = True
    st.rerun()

# =========================
# Sugestões rápidas (top buttons)
# =========================
st.subheader('Sugestões rápidas')

cols = st.columns(5)
COMMON_QUESTIONS = [
    'Quantas consultas foram feitas hoje?',
    'Qual foi a média de consultas nesse mês?',
    'Qual é o ranking de especialidades no mês anterior?',
    'Qual a média de idade nos últimos 3 meses?',
    'Top 5 especialidades médicas por sexo no mês anterior'
]

if st.session_state.show_suggestions:
    for i, q in enumerate(COMMON_QUESTIONS):
        if cols[i].button(q, use_container_width=True, key=f'quick_q_{i}'):
            st.session_state.pending_prompt = q
            st.session_state.show_suggestions = False
            st.session_state.is_processing = True
            st.rerun()

# =========================
# Render do histórico (sem steps / sem SQL)
# =========================
for message in st.session_state.history:
    role = message.get('role')
    content = message.get('content')

    if content is None or str(content).strip().lower() == 'none' or str(content).strip() == '':
        continue

    with st.chat_message(role):
        st.markdown(content)

# =========================
# Processamento da pending_prompt
# =========================
if st.session_state.is_processing and st.session_state.pending_prompt is not None and api_key:
    prompt = st.session_state.pending_prompt

    # Adiciona mensagem do usuário ao histórico
    st.session_state.history.append({'role': 'user', 'content': prompt})

    # Mostra balão do usuário desta interação
    with st.chat_message('user'):
        st.markdown(prompt)

    # Balão do assistente: aqui vamos animar steps e depois mostrar resposta
    with st.chat_message('assistant'):
        status = st.status('Analisando... 🧠', expanded=True)

        try:
            # Monta payload com history
            payload = {
                'prompt': prompt,
                'history': st.session_state.history  # histórico todo
            }

            headers = {
                'Content-Type': 'application/json',
                'X-API-Key': api_key,
                'X-User-Id': user_id,
                'X-Operadora': operadora,
            }

            # Chamada à API
            status.update(label='Consultando agente...', state='running')
            resp = requests.post(
                CHAT_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=120,
            )

            if resp.status_code != 200:
                status.update(label='Erro na API', state='error')
                st.error(f'Erro da API ({resp.status_code}): {resp.text}')
            else:
                data = resp.json()
                answer = data.get('answer', '')
                sql = data.get('sql')
                steps = data.get('steps', []) or []

                st.session_state.last_sql = sql

                # Placeholder interno dentro do status para timeline
                timeline_placeholder = st.empty()

                ICONS = {
                    'router': '🧭',
                    'tool_call': '🛠️',
                    'tool_result': '📊',
                    'llm': '🤖',
                }

                # Timeline cinematográfica DENTRO do balão do chat
                timeline_so_far = []
                for step in steps:
                    timeline_so_far.append(step)
                    with timeline_placeholder.container():
                        st.markdown('**🔍 Execução passo a passo**')
                        for s in timeline_so_far:
                            icon = ICONS.get(s.get('type'), '🔹')
                            line = f"{icon} **{s.get('type').upper()}**"
                            if s.get('tool'):
                                line += f" — `{s['tool']}`"
                            st.markdown(line)

                            msg = s.get('message')
                            if msg:
                                st.markdown(f"> {msg}")

                            args = s.get('args')
                            if args:
                                with st.expander('Args', expanded=False):
                                    st.json(args)

                    time.sleep(0.5)

                # Finaliza status
                status.update(label='Resposta gerada!', state='complete')

                # Some com a timeline e mostra só a resposta final
                timeline_placeholder.empty()
                st.markdown(answer)

                # Guarda a resposta no histórico
                st.session_state.history.append({'role': 'assistant', 'content': answer})

        except Exception as e:
            logging.error(f'Erro no processamento do chat: {e}', exc_info=True)
            status.update(label=f'Ocorreu um erro: {e}', state='error')
            st.error(f'Ocorreu um erro: {e}')

    # Limpa flags e volta para o input
    st.session_state.pending_prompt = None
    st.session_state.is_processing = False
    st.rerun()

# =========================
# SQL usada na última resposta
# =========================
st.markdown('---')
st.subheader('🧾 SQL usada na última resposta')

if st.session_state.last_sql:
    # Caso você tenha compactado a SQL em uma linha no back-end, ela já vem sem \n
    st.code(st.session_state.last_sql, language='sql')
else:
    st.caption('Nenhuma SQL registrada ainda. Faça uma pergunta que envolva dados para ver aqui.')