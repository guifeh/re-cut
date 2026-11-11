"""Fila local de publicação em um perfil dedicado do Chrome."""
import json
import os
import time
from pathlib import Path

import publicar


def habilitado():
    return bool(os.environ.get("RECUT_CHROME_PROFILE"))


def processar(jobs, postar):
    for registro in sorted(jobs.rglob("*.publicacao"), key=lambda p: p.name):
        corte = registro.with_suffix(".json")
        for plataforma in publicar.SOCIAIS_NAVEGADOR:
            if plataforma == "tiktok" and os.environ.get("RECUT_TIKTOK_PAUSADO") == "1":
                continue
            pub = publicar.envio_navegador_pendente(corte, plataforma)
            if pub is None:
                continue
            confirmou = False

            def antes_de_publicar():
                nonlocal confirmou
                if not registro.is_file() or not corte.is_file():
                    raise ValueError("corte removido")
                publicar.registrar_envio_navegador(
                    corte, plataforma, "incerto", "confira na rede antes de reenviar")
                confirmou = True

            try:
                meta = json.loads(corte.read_text(encoding="utf-8"))
                video = corte.with_name(meta["arquivo"]).resolve(strict=True)
                texto = publicar.texto_final(pub["legenda"], pub["hashtags"])
                postar(plataforma, video, texto, antes_de_publicar)
                if not confirmou:
                    raise ValueError("publicação não iniciada")
            except Exception as erro:
                mensagem = f"Chrome: {type(erro).__name__}. Confira a sessão e a tela da plataforma."
                publicar.registrar_envio_navegador(corte, plataforma, "incerto" if confirmou else "erro", mensagem)
            else:
                publicar.registrar_envio_navegador(corte, plataforma, "ok")


def abrir_chrome():
    from selenium import webdriver

    opcoes = webdriver.ChromeOptions()
    perfil = Path(os.environ["RECUT_CHROME_PROFILE"]).expanduser().resolve()
    opcoes.add_argument(f"--user-data-dir={perfil}")
    return webdriver.Chrome(options=opcoes)


def publicar_no_chrome(plataforma, video, texto, antes_de_publicar):
    from selenium.webdriver.common.by import By
    from selenium.webdriver.common.keys import Keys
    from selenium.webdriver.support.ui import WebDriverWait

    chrome = abrir_chrome()
    try:
        esperar = WebDriverWait(chrome, 35)

        def botao(*nomes):
            condicao = " or ".join(f"normalize-space(.)='{nome}'" for nome in nomes)
            xpath = f"//*[self::button or @role='button' or self::a][{condicao}]"
            return esperar.until(lambda d: next((e for e in d.find_elements(By.XPATH, xpath)
                                                 if e.is_displayed() and e.is_enabled()), None))

        if plataforma == "instagram":
            chrome.get("https://www.instagram.com/")
            botao("Create", "Criar").click()
        else:
            chrome.get("https://www.tiktok.com/tiktokstudio/upload")
        esperar.until(lambda d: d.find_element(By.CSS_SELECTOR, 'input[type="file"]')).send_keys(str(video))
        if plataforma == "instagram":
            for _ in range(2):
                botao("Next", "Avançar").click()
            seletor = '[role="dialog"] [contenteditable="true"]'
        else:
            seletor = '[contenteditable="true"][role="textbox"], .public-DraftEditor-content'
        campo = esperar.until(lambda d: next((e for e in d.find_elements(By.CSS_SELECTOR, seletor)
                                             if e.is_displayed()), None))
        campo.click()
        campo.send_keys(Keys.CONTROL, "a")
        chrome.execute_cdp_cmd("Input.insertText", {"text": texto})
        enviar = botao("Share", "Compartilhar") if plataforma == "instagram" else botao("Post", "Publicar")
        antes_de_publicar()
        enviar.click()
        mensagens = ("Your reel has been shared", "Seu reel foi compartilhado") if plataforma == "instagram" else (
            "Your video has been posted", "Seu vídeo foi publicado", "Video posted")
        WebDriverWait(chrome, 120).until(lambda d: any(m in d.find_element(By.TAG_NAME, "body").text for m in mensagens))
    finally:
        chrome.quit()


def ouvir(jobs):
    while True:
        try:
            processar(jobs, publicar_no_chrome)
        except (OSError, ValueError):
            pass
        time.sleep(5)


if __name__ == "__main__":
    chrome = abrir_chrome()
    try:
        chrome.get("https://www.instagram.com/")
        chrome.switch_to.new_window("tab")
        chrome.get("https://www.tiktok.com/")
        input("Entre nas duas contas no Chrome e pressione Enter para fechar. ")
    finally:
        chrome.quit()
