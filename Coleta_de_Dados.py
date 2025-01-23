import streamlit as st
import requests
from bs4 import BeautifulSoup
import pandas as pd
import re
import time

def converter_preco(preco_str):
    try:
        # Remove R$ e espaços
        preco_limpo = preco_str.replace('R$', '').replace(' ', '')
        # Substituir ponto por vazio (separador de milhar)
        preco_numerico = float(preco_limpo.replace('.', '').replace(',', '.'))
        return preco_numerico
    except (ValueError, AttributeError):
        return None

def extrair_dados_pagina(url):
    todos_dados = []
    
    progresso = st.progress(0)
    status = st.empty()
    
    headers = {
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
        'Accept-Language': 'pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7'
    }
    
    for pagina in range(1, 10):
        try:
            status.text(f"⏳ Processando página {pagina}/9")
            progresso.progress(pagina / 9)
            
            # Construir URL da página
            url_pagina = url + f'?pagina={pagina}' if pagina > 1 else url
            
            # Fazer requisição
            resposta = requests.get(url_pagina, headers=headers)
            resposta.raise_for_status()
            
            # Parsear HTML
            soup = BeautifulSoup(resposta.text, 'html.parser')
            
            # Encontrar cards de postagem
            cards = soup.find_all('div', class_='postingCardLayout-module__posting-card-layout__Lklt9')
            
            for card in cards:
                try:
                    # Extrair dados de cada card
                    dados = {
                        'card_id': card.get('data-id'),
                        'preco': converter_preco(card.select_one('[data-qa="POSTING_CARD_PRICE"]').text.strip()),
                        'localizacao': card.select_one('[data-qa="POSTING_CARD_LOCATION"]').text.strip(),
                        'endereco': card.select_one('.postingLocations-module__location-address__k8Ip7').text.strip(),
                        'area': int(re.search(r'\d+', card.select_one('.postingMainFeatures-module__posting-main-features-span__ror2o').text).group()),
                        'link': card.select_one('a')['href']
                    }
                    todos_dados.append(dados)
                except Exception as e:
                    st.warning(f"Erro no card: {str(e)}")
            
            # Tempo entre requisições para evitar bloqueio
            time.sleep(3)
        
        except Exception as e:
            st.error(f"Erro na página {pagina}: {str(e)}")
    
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
