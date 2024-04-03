from seleniumwire import webdriver
from selenium.webdriver.remote.webelement import WebElement
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.action_chains import ActionChains
from typing import Dict, List
from bs4 import BeautifulSoup
import time


def main1():
    def element_has_class(element, class_name):
        return class_name in element.get_attribute("class")

    def get_request_urls(browser: webdriver.Chrome):
        urls = []
        for request in browser.requests:
            if request.response:
                urls.append(request.url)

        return urls

    url = "https://bflix.gg/tv/watch-young-sheldon-39496"


    seasons: Dict[str, WebElement] = {}
    episodes: Dict[str, Dict[str, WebElement]] = {}

    browser = webdriver.Edge()
    browser.get(url)

    # soup = BeautifulSoup(browser.page_source, "html.parser")
    # open("soup.html", "w").write(soup.prettify())

    clickable = browser.find_element(By.CLASS_NAME, "slt-seasons-dropdown").find_elements(By.CSS_SELECTOR, "a.dropdown-item")
    for click in clickable:
        text_content = browser.execute_script("return arguments[0].innerText;", click)
        seasons[text_content] = (click, click.get_attribute("id").replace("-", "-episodes-"))


    for season in seasons:
        episodes[season] = {}
        browser.execute_script("arguments[0].click();", browser.find_element(By.CLASS_NAME, "slt-seasons-dropdown"))
        browser.execute_script("arguments[0].click();", seasons[season][0])
        wait = WebDriverWait(browser, 10)
        element: WebElement = wait.until(EC.presence_of_element_located((By.ID, seasons[season][1])))
        wait.until(lambda browser: element_has_class(element, "show"))
        time.sleep(1)

        episodes_elements: List[WebElement] = element.find_elements(By.CLASS_NAME, "nav-item")
        for episode in episodes_elements:
            episode = episode.find_element(By.TAG_NAME, "a")
            episodes[season][episode.get_attribute("title")] = episode


    browser.execute_script("arguments[0].click();", seasons[list(seasons.keys())[0]][0])
    browser.execute_script("arguments[0].click();", list(list(episodes.values())[0].values())[1])

    wait = WebDriverWait(browser, 10)
    element: WebElement = wait.until(EC.presence_of_element_located((By.ID, "modalshare")))

    sharing_window = browser.find_element(By.ID, "modalshare")
    close_btn = sharing_window.find_element(By.CSS_SELECTOR, "button.close")

    browser.execute_script("arguments[0].click();", close_btn)

    time.sleep(2)

    body = browser.find_element(By.TAG_NAME, "body")
    actions = ActionChains(browser)
    actions.move_to_element(body).click().perform()

    if len(browser.window_handles) > 1:
        browser.switch_to.window(browser.window_handles[1])
        browser.close()

    browser.switch_to.window(browser.window_handles[0])

    time.sleep(1)

    actions.move_to_element(body).click().perform()

    if len(browser.window_handles) > 1:
        browser.switch_to.window(browser.window_handles[1])
        browser.close()

    browser.switch_to.window(browser.window_handles[0])

    time.sleep(1)

    browser.execute_script("window.stop();")

    for entry in browser.requests:
        if entry.response:
            print(entry.url)
            print(entry.headers)
            print(len(entry.response.body))

    time.sleep(1000)

def main():
    url = "https://hurawatch.pro/tv/young-sheldon-j20oy/1-1"

    browser = webdriver.Edge()
    browser.get(url)

    time.sleep(1000)

if __name__ == "__main__":
    main()