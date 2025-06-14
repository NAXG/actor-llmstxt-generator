from apify import ProxyConfiguration
from crawlee import SkippedReason
from crawlee.crawlers import BeautifulSoupCrawler, BeautifulSoupCrawlingContext
from urllib.parse import urljoin

from src.helpers import get_description_from_soup, get_h1_from_soup, is_description_suitable
from src.mytypes import CrawledPage

STATUS_CODE_OK = 200


async def run_crawler(
    url: str, max_crawl_depth: int = 1, max_crawl_pages: int = 50, proxy: ProxyConfiguration | None = None,
    respect_robots_txt: bool = True
) -> list[CrawledPage]:
    """Runs the crawler and returns the results."""
    results: list[CrawledPage] = []

    # 首先创建 crawler 实例
    crawler_kwargs = {
        'max_crawl_depth': max_crawl_depth,
        'max_requests_per_crawl': max_crawl_pages,
        'respect_robots_txt_file': respect_robots_txt,
    }
    if proxy is not None:
        crawler_kwargs['proxy_configuration'] = proxy

    crawler = BeautifulSoupCrawler(**crawler_kwargs)  # type: ignore[arg-type]

    @crawler.router.default_handler
    async def request_handler(context: BeautifulSoupCrawlingContext) -> None:
        # 手动提取链接
        context.log.info(f'Processing {context.request.url}...')
        
        # 找到所有的<a>标签
        a_tags = context.soup.find_all('a', href=True)
        valid_urls = []
        
        for a_tag in a_tags:
            href = a_tag.get('href')
            if not href:
                continue
                
            # 将相对URL转换为绝对URL
            absolute_url = urljoin(context.request.url, href)
            
            # 过滤出以起始URL开头的链接
            if absolute_url.startswith(url) and absolute_url != context.request.url:
                valid_urls.append(absolute_url)
        
        # 添加有效链接到爬取队列
        if valid_urls:
            await context.add_requests(valid_urls)
            context.log.info(f'Found {len(valid_urls)} valid links to crawl')

        status_code = context.http_response.status_code
        if status_code != STATUS_CODE_OK:
            context.log.warning(f'Failed to fetch {context.request.url} with status code {status_code}')
            return

        title = get_h1_from_soup(context.soup) or context.soup.title.string if context.soup.title else None
        if not title:
            context.log.warning(f'No title found for {context.request.url}')
            return
        description = get_description_from_soup(context.soup)
        data: CrawledPage = {
            'url': context.request.url,
            'title': title,
            'description': description if is_description_suitable(description) else None,
        }
        results.append(data)

    # 处理被跳过的请求（在 crawler 创建之后使用装饰器）
    @crawler.on_skipped_request
    async def skipped_request_handler(url: str, reason: SkippedReason) -> None:
        # 检查是否是因为 robots.txt 规则被跳过
        if reason == 'robots_txt':
            crawler.log.warning(f'被 robots.txt 跳过的页面: {url}')

    await crawler.run([url])

    return results
