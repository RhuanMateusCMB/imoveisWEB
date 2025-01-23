import streamlit as st
from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.service import Service
from webdriver_manager.chrome import ChromeDriverManager
import random
import pandas as pd
import time

def get_random_user_agent():
   user_agents = [
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/119.0.0.0 Safari/537.36',
       'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/118.0.0.0 Safari/537.36'
   ]
   return random.choice(user_agents)

def configurar_navegador():
   opcoes_chrome = Options()
   opcoes_chrome.add_argument('--headless=new')
   opcoes_chrome.add_argument('--no-sandbox')
   opcoes_chrome.add_argument('--disable-dev-shm-usage')
   opcoes_chrome.add_argument('--window-size=1920,1080')
   opcoes_chrome.add_argument('--disable-blink-features=AutomationControlled')
   opcoes_chrome.add_argument('--enable-javascript')
   
   user_agent = get_random_user_agent()
   opcoes_chrome.add_argument(f'--user-agent={user_agent}')
   opcoes_chrome.add_argument('--accept-language=pt-BR,pt;q=0.9,en-US;q=0.8,en;q=0.7')
   
   opcoes_chrome.add_argument('--disable-notifications')
   opcoes_chrome.add_argument('--disable-popup-blocking')
   opcoes_chrome.add_argument('--disable-extensions')
   opcoes_chrome.add_argument('--disable-gpu')
   
   service = Service(ChromeDriverManager().install())
   navegador = webdriver.Chrome(service=service, options=opcoes_chrome)
   
   navegador.execute_cdp_cmd('Network.setUserAgentOverride', {
       "userAgent": user_agent,
       "platform": "Windows NT 10.0; Win64; x64"
   })
   
   navegador.execute_script("Object.defineProperty(navigator, 'webdriver', {get: () => undefined})")
   navegador.execute_script("Object.defineProperty(navigator, 'languages', {get: () => ['pt-BR', 'pt']})")
   navegador.execute_script("Object.defineProperty(navigator, 'plugins', {get: () => [1, 2, 3, 4, 5]})")
   
   return navegador

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
   
   for pagina in range(1, 10):
       driver = configurar_navegador()
       try:
           status.text(f"⏳ Processando página {pagina}/9")
           progresso.progress(pagina / 9)
           
           url_pagina = url + f'?pagina={pagina}' if pagina > 1 else url
           driver.get(url_pagina)
           
           WebDriverWait(driver, 45).until(
               EC.presence_of_element_located((By.CLASS_NAME, "postings-container"))
           )
           
           time.sleep(5)
           
           container = driver.find_element(By.CLASS_NAME, "postings-container")
           cards = container.find_elements(By.CLASS_NAME, "postingCardLayout-module__posting-card-layout__Lklt9")
           
           for card in cards:
               try:
                   preco_str = WebDriverWait(card, 10).until(
                       EC.presence_of_element_located((By.CSS_SELECTOR, '[data-qa="POSTING_CARD_PRICE"]'))
                   ).text
                   
                   area_str = WebDriverWait(card, 10).until(
                       EC.presence_of_element_located((By.CLASS_NAME, 'postingMainFeatures-module__posting-main-features-span__ror2o'))
                   ).text
                   
                   dados = {
                       'card_id': card.get_attribute('data-id'),
                       'preco': converter_preco(preco_str),
                       'localizacao': WebDriverWait(card, 10).until(
                           EC.presence_of_element_located((By.CSS_SELECTOR, '[data-qa="POSTING_CARD_LOCATION"]'))
                       ).text,
                       'endereco': card.find_element(By.CLASS_NAME, 'postingLocations-module__location-address__k8Ip7').text,
                       'area': int(area_str.split()[0]),
                       'link': card.find_element(By.CSS_SELECTOR, 'a').get_attribute('href')
                   }
                   todos_dados.append(dados)
               except Exception as e:
                   st.warning(f"Erro no card: {str(e)}")
           
           time.sleep(3)
       
       except Exception as e:
           st.error(f"Erro na página {pagina}: {str(e)}")
           driver.save_screenshot(f'error_page_{pagina}.png')
       
       finally:
           driver.quit()
   
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
