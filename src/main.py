"""This module defines the main entry point for the llsm.txt generator actor."""

import logging
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from apify import Actor

from src.crawler import run_crawler

from .helpers import (
    clean_llms_data,
    get_section_dir_title,
    get_url_path,
    get_url_path_dir,
    is_description_suitable,
    normalize_url,
)
from .renderer import render_llms_txt

if TYPE_CHECKING:
    from src.mytypes import LLMSData

logger = logging.getLogger('apify')

# section with less than this number of links will be moved to the index section
SECTION_MIN_LINKS = 2


async def main() -> None:
    """Main entry point for the llms.txt generator actor."""
    async with Actor:
        actor_input = await Actor.get_input()
        url = actor_input.get('startUrl')
        if url is None:
            msg = 'Missing "startUrl" attribute in input!'
            raise ValueError(msg)
        url_normalized = normalize_url(url)

        max_crawl_depth = int(actor_input.get('maxCrawlDepth', 1))
        max_crawl_pages = int(actor_input.get('maxCrawlPages', 50))
        respect_robots_txt = bool(actor_input.get('respectRobotsTxt', True))

        # proxy_config = await Actor.create_proxy_configuration()
        proxy_config = None
        results = await run_crawler(
            url=url, 
            max_crawl_depth=max_crawl_depth, 
            max_crawl_pages=max_crawl_pages, 
            proxy=proxy_config,
            respect_robots_txt=respect_robots_txt
        )

        hostname = urlparse(url).hostname
        root_title = hostname

        data: LLMSData = {'title': root_title, 'description': None, 'details': None, 'sections': {}}
        sections = data['sections']

        is_dataset_empty = True
        path_titles: dict[str, str] = {}
        sections_to_fill_title = []
        for item in results:
            is_dataset_empty = False
            if (item_url := item.get('url')) is None:
                logger.warning('Missing "url" attribute in dataset item!')
                continue
            logger.info(f'Processing page: {item_url}')

            description = item['description']
            title = item['title']
            path_titles[get_url_path(item_url)] = title

            # handle input root url separately
            is_root = normalize_url(item_url) == url_normalized
            if is_root:
                data['description'] = description if is_description_suitable(description) else None
                continue

            section_dir = get_url_path_dir(item_url)
            section_title = path_titles.get(section_dir)
            if section_dir not in sections:
                sections[section_dir] = {'title': section_title or section_dir, 'links': []}
                if section_title is None:
                    sections_to_fill_title.append(section_dir)

            sections[section_dir]['links'].append(
                {
                    'url': item_url,
                    'title': title,
                    'description': description if is_description_suitable(description) else None,
                }
            )

        if is_dataset_empty:
            # Check if robots.txt compliance is enabled
            if respect_robots_txt:
                logger.warning(f'Website {url} is completely blocked by robots.txt, generating informational llms.txt file')
                
                # Generate an informational llms.txt file
                data['description'] = f'This website ({url}) has a robots.txt file that disallows crawler access, making content extraction impossible.'
                data['details'] = f'To access this website\'s content, consider:\n1. Contacting the website administrator for permission\n2. Manually visiting the website for information\n3. Checking if the website provides an API'
                
                # Add an explanation section
                sections['robots-txt-blocked'] = {
                    'title': 'Robots.txt Access Restriction',
                    'links': [{
                        'url': f'{url}/robots.txt',
                        'title': 'robots.txt file',
                        'description': 'View the crawler access rules for this website'
                    }]
                }
                
                output = render_llms_txt(data)
                
                # save into kv-store as a file to be able to download it
                store = await Actor.open_key_value_store()
                await store.set_value('llms.txt', output)
                logger.info('Saved informational "llms.txt" file to key-value store!')

                await Actor.push_data({'llms.txt': output})
                logger.info('Pushed informational "llms.txt" file to dataset!')

                await Actor.set_status_message('Website blocked by robots.txt - generated informational llms.txt file')
                return
            else:
                # If robots.txt compliance is not enabled but still no content was crawled, raise original error
                msg = (
                    'No pages were crawled successfully!'
                    ' Please check the crawler configuration or target website accessibility.'
                )
                raise RuntimeError(msg)

        for section_dir in sections_to_fill_title:
            sections[section_dir]['title'] = get_section_dir_title(section_dir, path_titles)

        # move sections with less than SECTION_MIN_LINKS to the root
        clean_llms_data(data, section_min_links=SECTION_MIN_LINKS)
        output = render_llms_txt(data)

        # save into kv-store as a file to be able to download it
        store = await Actor.open_key_value_store()
        await store.set_value('llms.txt', output)
        logger.info('Saved the "llms.txt" file into the key-value store!')

        await Actor.push_data({'llms.txt': output})
        logger.info('Pushed the "llms.txt" file to the dataset!')

        await Actor.set_status_message('Finished! Saved the "llms.txt" file into the key-value store and dataset...')
