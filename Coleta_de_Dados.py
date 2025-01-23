import streamlit as st
from playwright.sync_api import sync_playwright
import pandas as pd
import time
import random

def get_random_user_agent():
   user_agents = [
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
   ]
   return random.choice(user_agents)

def converter_preco(preco_str):
    try:
        # Remove R$ and any spaces
        preco_limpo = preco_str.replace('R$', '').replace(' ', '')
        # Replace dot with empty string (for thousand separator)
        preco_numerico = float(preco_limpo.replace('.', '').replace(',', '.'))
        return preco_numerico
    except (ValueError, AttributeError):
        return None

def extrair_dados_pagina(url):
    todos_dados = []
    
    progresso = st.progress(0)
    status = st.empty()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        
        for pagina in range(1, 10):
            try:
                status.text(f"⏳ Processando página {pagina}/9")
                progresso.progress(pagina / 9)
                
                # Construir URL da página
                url_pagina = url + f'?pagina={pagina}' if pagina > 1 else url
                
                # Abrir página
                page = browser.new_page(user_agent=get_random_user_agent())
                page.goto(url_pagina, wait_until='networkidle')
                
                # Esperar pelo container de postagens
                page.wait_for_selector('.postings-container', timeout=45000)
                
                # Encontrar todos os cards de postagem
                cards = page.query_selector_all('.postingCardLayout-module__posting-card-layout__Lklt9')
                
                for card in cards:
                    try:
                        # Extrair dados de cada card
                        dados = {
                            'card_id': card.get_attribute('data-id'),
                            'preco': converter_preco(card.query_selector('[data-qa="POSTING_CARD_PRICE"]').inner_text()),
                            'localizacao': card.query_selector('[data-qa="POSTING_CARD_LOCATION"]').inner_text(),
                            'endereco': card.query_selector('.postingLocations-module__location-address__k8Ip7').inner_text(),
                            'area': int(card.query_selector('.postingMainFeatures-module__posting-main-features-span__ror2o').inner_text().split()[0]),
                            'link': card.query_selector('a').get_attribute('href')
                        }
                        todos_dados.append(dados)
                    except Exception as e:
                        st.warning(f"Erro no card: {str(e)}")
                
                # Tempo entre requisições para evitar bloqueio
                time.sleep(3)
                
                # Fechar página
                page.close()
            
            except Exception as e:
                st.error(f"Erro na página {pagina}: {str(e)}")
        
        # Fechar navegador
        browser.close()
    
    status.text("✅ Coleta concluída")
    progresso.progress(1.0)
    
    return todos_dados

def main():
    st.title('Extrator de Dados - Lotes em Eusébio')
    
    if st.button('Iniciar Extração'):
        with st.spinner('Extraindo...'):
            url = 'https://www.imovelweb.com.br/terrenos-venda-eusebio-ce.html'
            dados = extrair_dados_pagina(url)
            
            if dados:
                df = pd.DataFrame(dados)
                st.dataframe(df)
                st.download_button('Download CSV', df.to_csv(index=False).encode('utf-8'), 'lotes_eusebio.csv')
            else:
                st.error('Nenhum dado extraído')

if __name__ == '__main__':
   main()
