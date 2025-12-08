import os
import time
import json
import logging

import requests
import streamlit as st
from requests.exceptions import ChunkedEncodingError
from dotenv import load_dotenv

load_dotenv()

# =========================
# Configuração de logging
# =========================
logging.basicConfig(level=logging.INFO, format='%(levelname)s - %(message)s')

# =========================
# CONFIG BÁSICA
# =========================

API_BASE_URL = os.getenv('API_BASE_URL', 'http://163.176.236.162')
CHAT_STREAM_ENDPOINT_DEFAULT = f'{API_BASE_URL.rstrip("/")}/chat-stream'

DEFAULT_API_KEY = os.getenv('API_KEY')
DEFAULT_USER_ID = 'uni865'

# =========================
# Página
# =========================
st.set_page_config(
    page_title='Consultas',
    page_icon='🚀',
    layout='wide'
)
st.title('Saw Chat — Ambiente de Testes')

# =========================
# Sidebar — Configuração
# =========================
st.sidebar.header('Configuração da Sessão')

api_base_url = st.sidebar.text_input('API Base URL', value=API_BASE_URL)
chat_stream_endpoint = st.sidebar.text_input(
    'Endpoint /chat-stream',
    value=f'{api_base_url.rstrip("/")}/chat-stream'
)

api_key = st.sidebar.text_input('X-API-Key', value=DEFAULT_API_KEY, type='password')
user_id = st.sidebar.text_input('X-User-Id', value=DEFAULT_USER_ID)

st.sidebar.markdown('---')
st.sidebar.markdown('Headers enviados para a API:')

st.sidebar.code(
    f"POST {chat_stream_endpoint}\n"
    f"X-API-Key: {api_key or '...'}\n"
    f"X-User-Id: {user_id}",
    language='bash'
)

if not api_key:
    st.warning('⚠ Defina a X-API-Key na barra lateral para usar o agente.')

# =========================
# Estado de conversa
# =========================

# Histórico: lista de mensagens {role: 'user'/'assistant', content: str}
st.session_state.setdefault('history', [])

# Última SQL usada
st.session_state.setdefault('last_sql', None)

# Controle de UI
st.session_state.setdefault('show_suggestions', True)
st.session_state.setdefault('is_processing', False)
st.session_state.setdefault('pending_prompt', None)

# Se já houve alguma pergunta, não mostra mais sugestões
if any(msg.get('role') == 'user' for msg in st.session_state.history):
    st.session_state.show_suggestions = False

# =========================
# Input do chat (sempre visível)
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
# Sugestões rápidas
# =========================

st.subheader('Sugestões rápidas')

COMMON_QUESTIONS = [
    'Quantas consultas foram feitas hoje?',
    'Qual foi a média de consultas nesse mês?',
    'Qual é o ranking de especialidades no mês anterior?',
    'Valor total de consultas por prestador nos últimos 7 dias.',
    'Top 5 especialidades médicas por sexo no mês anterior',
]

cols = st.columns(len(COMMON_QUESTIONS))

if st.session_state.show_suggestions and api_key:
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

    if not content:
        continue

    with st.chat_message(role):
        st.markdown(content)

# =========================
# Processamento da pending_prompt (chamada /chat-stream)
# =========================

if st.session_state.is_processing and st.session_state.pending_prompt is not None and api_key:
    prompt = st.session_state.pending_prompt

    # 1) Adiciona mensagem do usuário ao histórico
    st.session_state.history.append({'role': 'user', 'content': prompt})

    # 2) Mostra balão do usuário desta interação
    with st.chat_message('user'):
        st.markdown(prompt)

    # 3) Balão do assistente (status + resposta em streaming)
    with st.chat_message('assistant'):
        status = st.status('Analisando... 🧠', expanded=True)

        try:
            # Monta payload
            payload = {
                'prompt': prompt,
                'history': st.session_state.history,  # histórico todo
            }

            headers = {
                'Content-Type': 'application/json',
                'X-API-Key': api_key,
                'X-User-Id': user_id,
            }

            status.update(label='Enviando pergunta ao agente...', state='running')

            # stream=True para ler NDJSON linha a linha
            resp = requests.post(
                chat_stream_endpoint,
                json=payload,
                headers=headers,
                timeout=120,
                stream=True,
            )

            if resp.status_code != 200:
                error_body = resp.text
                status.update(label='Erro na API', state='error')
                st.error(f'Erro da API ({resp.status_code}): {error_body}')
            else:
                # Placeholders para status e resposta
                status_text = st.empty()       # mostra o que o agente está fazendo
                answer_placeholder = st.empty()

                answer_buffer = ""

                # Mapeamento de mensagens amigáveis por tipo de step
                def describe_step(step: dict) -> str:
                    stype = step.get('type', 'step')
                    tool = step.get('tool')

                    if stype == 'router':
                        return "Entendendo qual métrica e ferramenta usar..."
                    if stype == 'tool_call':
                        if tool == 'get_total_consultas':
                            return "Calculando o total de consultas..."
                        if tool == 'get_media_consultas_diaria':
                            return "Calculando a média diária de consultas..."
                        if tool == 'get_ranking_especialidades':
                            return "Montando o ranking de especialidades..."
                        if tool == 'get_ranking_tipo_atendimento':
                            return "Montando o ranking de tipos de prestador..."
                        if tool == 'run_generic_text_to_sql_query':
                            return "Gerando e executando uma consulta SQL nos dados..."
                        return f"Utilizando a ferramenta '{tool}'..."
                    if stype == 'tool_result':
                        return "Resultados obtidos. Preparando explicação..."
                    if stype == 'llm':
                        return "Organizando ideias..."
                    return "🔄 Processando sua solicitação..."

                try:
                    for raw_line in resp.iter_lines(decode_unicode=True):
                        if not raw_line:
                            continue

                        try:
                            event = json.loads(raw_line)
                        except Exception:
                            logging.warning(f'Linha inválida no stream: {raw_line}')
                            continue

                        etype = event.get('type')

                        if etype == 'start':
                            msg = event.get('message', 'Iniciando processamento...')
                            status.update(label=msg, state='running')

                        elif etype == 'step':
                            step = event.get('step', {})
                            friendly = describe_step(step)
                            status.update(label=friendly, state='running')

                        elif etype == 'answer_delta':
                            delta_text = event.get('text', '')
                            if delta_text:
                                answer_buffer += delta_text
                                # Vai atualizando a resposta "digitando"
                                answer_placeholder.markdown(answer_buffer)

                        elif etype == 'answer_final':
                            final_answer = event.get('answer') or answer_buffer
                            sql = event.get('sql')
                            download_url = event.get('download_url')  # BACKEND TRATA export_csv E JÁ MANDA AQUI

                            # Atualiza status
                            status.update(label='Resposta gerada!', state='complete')
                            status_text.empty()

                            # Mostra texto da resposta
                            answer_placeholder.markdown(final_answer)

                            # Se existir download_url → usar download_button
                            if download_url:
                                st.markdown("### 📄 Baixar relatório CSV")

                                # Tenta fazer download do arquivo aqui no backend do Streamlit
                                try:
                                    import requests
                                    file_response = requests.get(download_url)
                                    file_response.raise_for_status()
                                    file_bytes = file_response.content

                                    st.download_button(
                                        label="⬇️ Download do arquivo CSV",
                                        data=file_bytes,
                                        file_name=download_url.split("/")[-1],
                                        mime="text/csv",
                                    )

                                except Exception as e:
                                    st.error(f"Erro ao baixar arquivo: {e}")

                            # Atualiza histórico
                            st.session_state.history.append(
                                {'role': 'assistant', 'content': final_answer}
                            )
                            st.session_state.last_sql = sql

                            break

                        time.sleep(0.05)

                except ChunkedEncodingError:
                    status.update(label='Conexão encerrada pelo servidor.', state='error')
                    st.error('A resposta foi interrompida antes de terminar. Tente novamente.')

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
    st.code(st.session_state.last_sql, language='sql')
else:
    st.caption('Nenhuma SQL registrada ainda. Faça uma pergunta que envolva dados para ver aqui.')
