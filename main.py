import re
from urllib import parse

import time
import base64
import pangu
import requests
from tomd import Tomd
from bs4 import BeautifulSoup as bs
from loguru import logger
from pyquery import PyQuery
from requests.packages.urllib3.exceptions import InsecureRequestWarning

requests.packages.urllib3.disable_warnings(InsecureRequestWarning)


class ZsxqSpider(object):
    def __init__(self):
        self.delay = 0
        self.b64 = False
        self.group_id = "*************"

        self.headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/87.0.4280.88 Safari/537.36 Edg/87.0.664.66",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,image/apng,*/*;q=0.8,application/signed-exchange;v=b3;q=0.9",
            "Accept-Language": "zh-CN,zh;q=0.9,und;q=0.8,en;q=0.7",
            "cookie": r"*******************"
        }
        self.digests_url = f"https://api.zsxq.com/v2/groups/{self.group_id}/topics/digests"
        self.index = "0"
        self.latest_time = None
        self.params = {
            "sort": "by_create_time",
            "direction": "desc",
            "count": "30",
            "index": self.index,
        }
        self.response = dict()
        self.md_list = []
        self.count = 0

    def crawler(self):
        self.params["index"] = self.index
        while True:
            time.sleep(self.delay)
            self.response = requests.get(
                url=self.digests_url, headers=self.headers, verify=False, params=self.params
            ).json()
            if self.response.get("succeeded"):
                logger.info(f"列表: {self.group_id} {self.index} 完成")
                break
            else:
                logger.error(f"列表: {self.group_id} {self.index} 错误")

    def parse_topics(self):
        topics = self.response.get("resp_data", {}).get("topics", [])
        self.index = self.response.get("resp_data", {}).get("index")
        self.index = str(self.index)
        self.count += len(topics)
        for t in topics:
            topic_id = t.get("topic_id")
            topic_url = f"https://api.zsxq.com/v2/topics/{topic_id}/info"
            while True:
                time.sleep(self.delay)
                response = requests.get(url=topic_url, headers=self.headers).json()
                if response.get("succeeded"):
                    topic = response.get("resp_data", {}).get("topic", {})
                    logger.info(f"主题: {t.get('title')[:15]} 完成")
                    break
                else:
                    logger.error(f"主题: {t.get('title')[:15]} 错误")
            md = []
            topic_type = topic.get("type")
            md.append(self.parse_header(topic))
            if topic_type == "talk":
                md += self.parse_talk(topic)
            elif topic_type == "q&a":
                md += self.parse_qa(topic)
            else:
                self.count -= 1
                continue
            md.append(self.parse_comment(topic))
            md_text = "\n".join(md)
            self.md_list.append(md_text)
        logger.info(f"{self.group_id} {self.count} 😀😆")
        return True

    def parse_file(self, name, id):
        while True:
            time.sleep(self.delay)
            download_url = f"https://api.zsxq.com/v2/files/{id}/download_url"
            response = requests.get(url=download_url, headers=self.headers).json()
            if response.get("succeeded"):
                file_url = response.get("resp_data", {}).get("download_url")
                break
            else:
                logger.error(f"文件: {name} 错误")
        with open(name, 'w') as f:
            f.write(requests.get(url=file_url, headers=self.headers))
    
    def parse_article(self, url):
        html = requests.get(url=url, headers=self.headers).text
        html = bs(html, features="lxml")
        html = html.find("div", class_="content")
        md = Tomd(str(html)).markdown
        md = md.replace("\n", "")
        return md

    def parse_html(self, content):
        content = content.replace("\n", "<br>")
        result = re.findall(r"<e [^>]*>", content)
        if result:
            for i in result:
                html = PyQuery(i)
                if html.attr("type") == "web":
                    title = parse.unquote(html.attr("title"))
                    url = parse.unquote(html.attr("href"))
                    template = "[%s](%s)" % (title, url)
                    template += f"\n## {title}\n"
                    template += self.parse_article(url)
                    template += "\n"
                elif html.attr("type") == "hashtag":
                    template = " `%s` " % parse.unquote(html.attr("title"))
                elif html.attr("type") == "mention":
                    template = parse.unquote(html.attr("title"))
                else:
                    template = i
                content = content.strip().replace(i, template)
        else:
            content = pangu.spacing_text(content)
        return content
    
    def img2b64(self, img):
        try:
            url = img.get("original").get("url")
        except Exception:
            url = img.get("large").get("url")
        if not self.b64:
            return url
        type_ = img.get("type")
        img = requests.get(url=url, headers=self.headers).content
        b64 = base64.b64encode(img).decode()
        b64 = "data:image/" + type_ + ";base64," + b64
        return b64

    def parse_header(self, topic):
        data_time = topic["create_time"]
        # group = topic.get("group", {}).get("name")
        author = topic.get("talk", {}).get("owner", {}).get("name")
        return f"# {author} - {data_time.split('T')[0]}"

    def parse_comment(self, topic):
        comments = [
            comment.get("owner").get("name") + ": " + self.parse_html(comment.get("text", ""))
            for comment in topic.get("show_comments", [])
        ]
        # comment_text = "```\n" + "\n".join(comments) + "\n```\n\n" if comments else ""
        comment_text = "> \n" + "\n".join(comments) + "\n\n\n" if comments else ""
        return comment_text

    def parse_qa(self, topic):
        question_text = self.parse_html(topic.get("question", {}).get("text", ""))
        answer_text = self.parse_html(topic.get("answer", {}).get("text", ""))
        question_images = []
        if topic.get("question").get("images"):
            for img in topic.get("question").get("images"):
                b64 = self.img2b64(img)
                question_images.append(b64)
        answer_images = []
        if topic.get("answer").get("images"):
            for img in topic.get("answer").get("images"):
                b64 = self.img2b64(img)
                answer_images.append(b64)

        question_image_text = "\n".join([f"![]({question_image})" for question_image in question_images])
        answer_image_text = "\n".join([f"![]({answer_image})" for answer_image in answer_images])
        md = ["## 问:", question_text, question_image_text, "## 答:", answer_text, answer_image_text]
        return md

    def parse_talk(self, topic):
        content = self.parse_html(topic.get("talk", {}).get("text", ""))
        images = []
        if topic.get("talk").get("images"):
            for img in topic.get("talk").get("images"):
                b64 = self.img2b64(img)
                images.append(b64)

        image_text = "\n".join([f"![]({image})" for image in images])
        md = [content, image_text]
        return md

    def run(self):
        while True:
            self.crawler()
            self.parse_topics()
            if self.index == "0":
                break
        text = "\n".join(self.md_list[::-1])
        logger.info(f"写入 {self.group_id}.md")
        with open(f"data/{self.group_id}.md", "w", encoding='utf8') as f:
            f.write(text)
        logger.info(f"{self.group_id} 抓取完成  {self.count} 主题")


if __name__ == "__main__":
    zsxq = ZsxqSpider()
    zsxq.run()
