import os
import logging
import json
import re
import asyncio
from playwright.async_api import async_playwright
from bs4 import BeautifulSoup
import zoneinfo
import tzlocal
from python_utils import converters
import cloudscraper
import time
from PIL import Image as PILImage

from astrbot.api.event import filter, AstrMessageEvent
from astrbot.api.star import Context, Star, register
from astrbot.api.message_components import Plain, Image
from astrbot.api.all import *

HLTV_COOKIE_TIMEZONE = "Europe/Copenhagen"
HLTV_ZONEINFO = zoneinfo.ZoneInfo(HLTV_COOKIE_TIMEZONE)
LOCAL_TIMEZONE_NAME = tzlocal.get_localzone_name()
LOCAL_ZONEINFO = zoneinfo.ZoneInfo(LOCAL_TIMEZONE_NAME)

@register(
    name="hltv_query",  # 插件名称要与文件夹名称一致
    author="advent148259",
    version="1.0.0",
    desc="HLTV比赛信息查询插件"  # 添加描述参数
)
class HLTVQuery(Star):
    def __init__(self, context: Context, config: dict = None):
        super().__init__(context)
        self.config = config or {}
        
        # 修改 teams_file 路径
        self.teams_file = os.path.join(os.path.dirname(__file__), "teams.txt")
        
        # 定义命令帮助信息
        self.commands_help = {
            "hltv_help": {
                "command": "/hltv_help",
                "desc": "显示所有可用的HLTV查询指令",
                "usage": "/hltv_help",
                "category": "帮助"
            },
            
            # 战队相关指令
            "hltv排名": {
                "command": "/hltv排名",
                "desc": "查询HLTV世界排名前5的战队,含阵容信息", 
                "usage": "/hltv排名",
                "category": "战队" 
            },
            "top5": {
                "command": "/top5",
                "desc": "快速查看HLTV TOP5战队列表",
                "usage": "/top5", 
                "category": "战队"
            },
            "top30": {
                "command": "/top30",
                "desc": "查看HLTV TOP30战队完整排名",
                "usage": "/top30",
                "category": "战队"
            },
            "战队信息": {
                "command": "/战队信息 [战队名称]",
                "desc": "查询指定战队的详细统计数据",
                "usage": "/战队信息 Natus Vincere", 
                "category": "战队"
            },
            
            # 比赛相关指令 
            "比赛": {
                "command": "/比赛",
                "desc": "查询HLTV近期即将进行的比赛(10场)",
                "usage": "/比赛",
                "category": "比赛"  
            },
            "结果": {
                "command": "/结果", 
                "desc": "查询HLTV近期比赛结果(10场)\n在显示结果后30秒内输入编号(1-10)可查看详细数据",
                "usage": "/结果",
                "category": "比赛"
            },

            # 选手相关指令
            "top选手": {
                "command": "/top选手",
                "desc": "查询HLTV TOP10选手排名",
                "usage": "/top选手",
                "category": "选手"
            },
            "搜索选手": {
                "command": "/搜索选手 [选手名称]",
                "desc": "搜索选手,显示前5个匹配结果\n在30秒内输入序号(1-5)可查看选手详细数据",
                "usage": "/搜索选手 ZywOo",
                "category": "选手"
            },
            "选手详情": {
                "command": "/选手详情 [选手ID]", 
                "desc": "查询指定选手ID的详细统计数据",
                "usage": "/选手详情 12345",
                "category": "选手"
            }
        }
        
        # 配置日志记录器
        self.logger = logging.getLogger(__name__)
        self.logger.setLevel(logging.DEBUG)
        
        # 创建控制台处理器
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.DEBUG)
        
        # 创建格式化器
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s',  # 修改 level别名 为 levelname
            datefmt='%Y-%m-%d %H:%M:%S'
        )
        console_handler.setFormatter(formatter)
        
        # 添加处理器到日志记录器
        self.logger.addHandler(console_handler)
        
        self.team_map = []
        # 存储最近查询的比赛信息
        self.recent_matches = {}
        # 存储用户最后查询结果的时间
        self.last_result_query = {}
        
        # 添加新属性用于存储搜索结果和查询时间
        self.player_search_results = {}  # 存储用户搜索到的选手信息
        self.last_search_time = {}      # 存储用户最后搜索时间
        
        # 添加截图保存路径
        self.screenshot_dir = os.path.join(os.path.dirname(__file__), "screenshots")
        if not os.path.exists(self.screenshot_dir):
            os.makedirs(self.screenshot_dir, exist_ok=True)

    async def get_parsed_page(self, url):
        """每次请求都使用新的浏览器实例"""
        try:
            self.logger.info(f"正在请求URL: {url}")
            
            async with async_playwright() as playwright:
                # 每次创建新的浏览器实例
                browser = await playwright.chromium.launch(
                    headless=True,
                )
                
                # 创建新的上下文，使用随机用户代理
                context = await browser.new_context(
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                    viewport={'width': 1920, 'height': 1080},
                )
                
                # 创建新页面
                page = await context.new_page()
                self.logger.debug("已创建新页面")
                
                try:
                    # 在page.goto之前添加
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.localStorage.setItem('CookieConsent', JSON.stringify({
                            accepted: true,
                            necessary: true,
                            preferences: true,
                            statistics: true,
                            marketing: true
                        }));
                    """)
                    
                    # 设置超时时间
                    page.set_default_timeout(60000)
                    
                    # 访问页面
                    self.logger.debug("开始访问页面...")
                    response = await page.goto(url, wait_until="networkidle")
                    
                    if not response or response.status != 200:
                        self.logger.error(f"页面加载失败：状态码 {response.status if response else 'None'}")
                        return None
                    
                    # 等待页面加载
                    await page.wait_for_load_state("domcontentloaded")
                    await asyncio.sleep(2)
                    
                    # 页面加载后,截图前添加
                    await page.evaluate("""() => {
                        const cookiebot = document.getElementById('CybotCookiebotDialog');
                        if (cookiebot) cookiebot.remove();
                        
                        const cookieBanner = document.querySelector('.CookieDeclaration');
                        if (cookieBanner) cookieBanner.remove();
                        
                        const possibleSelectors = [
                            '#CybotCookiebotDialogBodyUnderlay',
                            '.cookiebot-overlay',
                            '[class*="cookie-notice"]',
                            '[class*="cookie-banner"]',
                            '[id*="cookie-banner"]',
                            '[id*="cookie-notice"]'
                        ];
                        
                        possibleSelectors.forEach(selector => {
                            const elements = document.querySelectorAll(selector);
                            elements.forEach(el => el.remove());
                        });
                        
                        window.CookieConsent = {
                            consent: {
                                stamp: '0',
                                necessary: true,
                                preferences: true,
                                statistics: true,
                                marketing: true
                            }
                        };
                    }""")
                    
                    # 获取内容
                    content = await page.content()
                    
                    if not content:
                        self.logger.error("获取到的页面内容为空")
                        return None
                        
                    self.logger.debug(f"页面内容长度: {len(content)}")
                    
                    # 解析内容
                    soup = BeautifulSoup(content, "lxml")
                    
                    if not soup.find():
                        self.logger.error("BeautifulSoup解析结果为空")
                        return None
                        
                    return soup
                    
                except Exception as e:
                    self.logger.error(f"处理页面时发生错误: {str(e)}")
                    self.logger.debug("异常详情: ", exc_info=True)
                    return None
                finally:
                    # 关闭所有资源
                    await page.close()
                    await context.close()
                    await browser.close()
                    self.logger.debug("已关闭所有浏览器资源")
                    
        except Exception as e:
            self.logger.error(f"请求或解析页面时发生错误: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            return None

    async def get_all_teams(self):
        """获取所有队伍信息并保存到文件"""
        try:
            # 如果有缓存文件，先尝试读取
            if os.path.exists(self.teams_file):
                self.logger.info("从缓存文件读取战队信息...")
                try:
                    with open(self.teams_file, 'r', encoding='utf-8') as f:
                        for line in f:
                            try:
                                team_id, team_name, team_url = line.strip().split('|')
                                team_info = {
                                    'id': int(team_id),
                                    'name': team_name,
                                    'url': team_url
                                }
                                self.team_map.append(team_info)
                            except Exception as e:
                                self.logger.error(f"解析缓存行出错: {str(e)}")
                                continue
                    self.logger.info(f"从缓存读取了 {len(self.team_map)} 支战队的信息")
                    return self.team_map
                except Exception as e:
                    self.logger.error(f"读取缓存文件失败: {str(e)}")
                    # 如果读取失败，清空列表以便重新获取
                    self.team_map = []

            # 如果没有缓存或读取失败，从网站获取
            if not self.team_map:
                self.logger.info("正在从HLTV获取所有战队信息...")
                teams_page = await self.get_parsed_page("https://www.hltv.org/stats/teams?minMapCount=0")
                if not teams_page:
                    self.logger.error("获取战队列表失败")
                    return []
                    
                # 创建或覆盖文件
                with open(self.teams_file, 'w', encoding='utf-8') as f:
                    for team in teams_page.find_all("td", {"class": ["teamCol-teams-overview"]}):
                        try:
                            team_id = int(team.find("a")["href"].split("/")[-2])
                            team_name = team.find("a").text.strip()
                            team_url = "https://hltv.org" + team.find("a")["href"]
                            
                            # 保存到内存
                            team_info = {
                                'id': team_id,
                                'name': team_name,
                                'url': team_url
                            }
                            self.team_map.append(team_info)
                            
                            # 写入文件
                            f.write(f"{team_id}|{team_name}|{team_url}\n")
                            self.logger.debug(f"添加并保存战队: {team_name} (ID: {team_id})")
                        except Exception as e:
                            self.logger.error(f"解析战队信息失败: {str(e)}")
                            continue
                            
                self.logger.info(f"成功获取并保存 {len(self.team_map)} 支战队的信息")
                
            return self.team_map
            
        except Exception as e:
            self.logger.error(f"获取战队列表时发生错误: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            return []

    async def find_team_id(self, team_name: str):
        """查找队伍ID"""
        teams = await self.get_all_teams()
        for team in teams:
            if team['name'].lower() == team_name.lower():
                return team['id']
        return None

    @filter.command("hltv_help")
    async def show_help(self, event: AstrMessageEvent):
        """显示HLTV查询插件的帮助信息"""
        help_text = "🎮 HLTV 查询插件帮助菜单 🎮\n" + "═" * 30 + "\n\n"
        
        # 分类指令
        team_commands = {
            "top5战队": {
                "command": "/top5战队",
                "desc": "查询HLTV世界排名前5的战队,含阵容信息",
                "usage": "/top5战队"
            },
            "战队信息": {
                "command": "/战队信息 [战队名称]",
                "desc": "查询指定战队的详细统计数据",
                "usage": "/战队信息 Natus Vincere"
            }
        }
        
        match_commands = {
            "近期比赛": {
                "command": "/近期比赛",
                "desc": "查询HLTV近期即将进行的比赛(10场)",
                "usage": "/近期比赛"
            },
            "比赛结果": {
                "command": "/比赛结果",
                "desc": "查询HLTV近期比赛结果(10场)\n在30秒内输入字母(a-e)可查看详细数据",
                "usage": "/比赛结果"
            }
        }
        
        player_commands = {
            "top选手": {
                "command": "/top选手",
                "desc": "查询HLTV TOP10选手排名",
                "usage": "/top选手"
            },
            "搜索选手": {
                "command": "/搜索选手 [选手名称]",
                "desc": "搜索选手,显示前5个匹配结果\n在30秒内输入序号(1-5)可查看选手详细数据",
                "usage": "/搜索选手 ZywOo"
            }
        }
        
        # 战队相关指令
        help_text += "🏆 战队查询\n" + "─" * 20 + "\n"
        for cmd, info in team_commands.items():
            help_text += f"📍 {info['command']}\n"
            help_text += f"  💡 说明: {info['desc']}\n"
            help_text += f"  📝 用法: {info['usage']}\n\n"
        
        # 比赛相关指令
        help_text += "⚔️ 比赛查询\n" + "─" * 20 + "\n"
        for cmd, info in match_commands.items():
            help_text += f"📍 {info['command']}\n"
            help_text += f"  💡 说明: {info['desc']}\n"
            help_text += f"  📝 用法: {info['usage']}\n\n"
        
        # 选手相关指令
        help_text += "👤 选手查询\n" + "─" * 20 + "\n"
        for cmd, info in player_commands.items():
            help_text += f"📍 {info['command']}\n"
            help_text += f"  💡 说明: {info['desc']}\n"
            help_text += f"  📝 用法: {info['usage']}\n\n"
        
        help_text += "📌 提示：\n"
        help_text += "• 所有命令前都需要加'/'符号\n"
        help_text += "• 部分查询可能需要一定时间，请耐心等待\n"
        help_text += "• 数据来源于 HLTV.org\n"
        help_text += "\n❓ 如有问题请联系插件作者：advent148259"
        
        yield event.plain_result(help_text)

    @filter.command("top5战队")
    async def query_top_teams(self, event: AstrMessageEvent):
        """查询HLTV世界排名前5的战队"""
        yield event.plain_result("🔍 正在查询HLTV世界排名，请稍候...")
        
        try:
            page = await self.get_parsed_page("https://www.hltv.org/ranking/teams/")
            if not page:
                yield event.plain_result("❌ 获取排名信息失败，请稍后重试")
                return
                
            teams = page.find("div", {"class": "ranking"})
            if not teams:
                self.logger.error("未找到ranking div元素")
                yield event.plain_result("❌ 解析排名信息失败")
                return
            
            ranked_teams = teams.find_all("div", {"class": "ranked-team standard-box"})
            if not ranked_teams:
                self.logger.error("未找到ranked-team元素")
                yield event.plain_result("❌ 未找到排名信息")
                return
            
            result = "🏆 HLTV世界排名TOP5 🏆\n" + "═" * 30 + "\n"
            for team in ranked_teams[:5]:
                try:
                    name_element = team.find('div', {"class": "ranking-header"}).select('.name')
                    if not name_element:
                        self.logger.error("未找到战队名称元素")
                        continue
                        
                    name = name_element[0].text.strip()
                    
                    rank_element = team.select('.position')
                    if not rank_element:
                        self.logger.error("未找到排名元素")
                        continue
                        
                    rank = rank_element[0].text.strip()
                    
                    points_element = team.find('span', {'class': 'points'})
                    if not points_element:
                        self.logger.error("未找到积分元素")
                        continue
                        
                    points = points_element.text
                    
                    result += f"\n{'🥇' if rank == '1' else '🥈' if rank == '2' else '🥉' if rank == '3' else '🏅'} #{rank} {name}\n"
                    result += f"📊 积分: {points}\n"
                    
                    # 添加队伍阵容信息
                    players = []
                    for player in team.find_all("td", {"class": "player-holder"}):
                        player_img = player.find('img', {'class': 'playerPicture'})
                        if player_img and player_img.get('title'):
                            players.append(player_img['title'])
                    
                    if players:
                        result += f"👥 阵容: {', '.join(players)}\n"
                    result += "─" * 25 + "\n"
                    
                except Exception as e:
                    self.logger.error(f"处理单个战队信息时出错: {str(e)}")
                    continue
            
            if result == "🏆 HLTV世界排名TOP5 🏆\n" + "═" * 30 + "\n":
                yield event.plain_result("❌ 解析排名信息失败，请稍后重试")
            else:
                yield event.plain_result(result)
            
        except Exception as e:
            self.logger.error(f"查询排名失败: {str(e)}")
            yield event.plain_result("❌ 查询排名信息失败，请稍后重试")

    @filter.command("战队信息")
    async def query_team_info(self, event: AstrMessageEvent, *, team_name: str):
        """查询指定战队的信息"""
        self.logger.info(f"收到战队信息查询请求: {team_name}")
        yield event.plain_result(f"🔍 正在查询 {team_name} 的信息，请稍候...")
        
        try:
            team_id = await self.find_team_id(team_name)
            if not team_id:
                self.logger.warning(f"未找到战队: {team_name}")
                yield event.plain_result(f"❌ 未找到战队 {team_name} 的信息")
                return

            self.logger.info(f"找到战队ID: {team_id}, 正在获取详细信息")
            page = await self.get_parsed_page(f"https://www.hltv.org/?pageid=179&teamid={team_id}")
            
            if not page:
                self.logger.error("获取战队详情页面失败")
                yield event.plain_result("❌ 获取战队信息失败，请稍后重试")
                return
            
            # 获取战队名称
            team_name = page.find("div", {"class": "context-item"})
            if not team_name:
                self.logger.error("无法找到战队名称元素")
                yield event.plain_result("❌ 解析战队信息失败，请稍后重试")
                return
            team_name = team_name.text
            
            # 获取战队统计信息
            self.logger.info("正在解析战队统计数据")
            team_stats = {}
            stats_columns = page.find_all("div", {"class": "columns"})
            for columns in stats_columns:
                try:
                    stats = columns.find_all("div", {"class": "col standard-box big-padding"})
                    for stat in stats:
                        stat_value = stat.find("div", {"class": "large-strong"}).text
                        stat_title = stat.find("div", {"class": "small-label-below"}).text
                        team_stats[stat_title] = stat_value
                        self.logger.debug(f"统计数据: {stat_title} = {stat_value}")
                except Exception as e:
                    self.logger.error(f"解析统计数据时出错: {str(e)}")
                    self.logger.debug("异常详情: ", exc_info=True)

            # 获取当前阵容
            self.logger.info("正在解析当前阵容信息")
            current_lineup = []
            for player in page.find_all("div", {"class": "col teammate"})[:5]:
                try:
                    name = player.find("img", {"class": "container-width"})["alt"].split("'")
                    nickname = player.find("div", {"class": "text-ellipsis"}).text
                    maps = re.search(r'\d+', player.find("div", {"class": "teammate-info standard-box"}).find("span").text).group()
                    player_info = {
                        "name": name[0].rstrip() + name[2],
                        "nickname": nickname,
                        "maps_played": maps
                    }
                    current_lineup.append(player_info)
                    self.logger.debug(f"添加选手: {player_info}")
                except Exception as e:
                    self.logger.error(f"解析选手信息时出错: {str(e)}")
                    self.logger.debug("异常详情: ", exc_info=True)
                    continue

            # 构建输出信息
            self.logger.info("正在生成输出信息")
            result = f"🎮 {team_name} 战队信息\n" + "═" * 30 + "\n\n"
            
            result += "📊 统计数据:\n" + "─" * 20 + "\n"
            for title, value in team_stats.items():
                result += f"• {title}: {value}\n"
            
            result += "\n👥 当前阵容:\n" + "─" * 20 + "\n"
            for i, player in enumerate(current_lineup, 1):
                result += f"{i}. {player['nickname']} ({player['name']})\n"
                result += f"   📈 比赛场数: {player['maps_played']}\n"

            self.logger.info("查询完成，正在返回结果")
            yield event.plain_result(result)

             # 构建完基本信息后，使用 playwright 进行截图
            async with async_playwright() as playwright:
                browser= await playwright.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
                )
                
                page = await context.new_page()
                
                try:
                    url = f"https://www.hltv.org/team/{team_id}/{team_name}"
                    self.logger.info(f"准备访问URL: {url}")
                    
                    # 记录请求开始时间
                    start_time = time.time()
                    
                    # 访问页面
                    response = await page.goto(url, wait_until="networkidle")
                    
                    # 记录响应状态
                    if response:
                        self.logger.info(f"页面响应状态码: {response.status}")
                        self.logger.info(f"页面请求耗时: {time.time() - start_time:.2f}秒")
                    else:
                        self.logger.error("未收到页面响应")
                        raise Exception("页面访问失败")

                    # 等待页面加载
                    self.logger.info("等待页面加载完成...")
                    await page.wait_for_load_state("domcontentloaded")
                    self.logger.info("页面DOM加载完成")
                    
                    await asyncio.sleep(2)
                    self.logger.info("额外等待2秒完成")

                    # 检查页面内容
                    content = await page.content()
                    self.logger.info(f"页面内容长度: {len(content)} 字节")
                    
                    # 检查关键元素是否存在
                    columns_count = await page.evaluate("""() => {
                        return document.querySelectorAll('.columns').length;
                    }""")
                    self.logger.info(f"找到 {columns_count} 个columns元素")
    
                    # 移除cookie相关元素
                    await page.evaluate("""() => {
                        const style = document.createElement('style');
                        style.textContent = `
                            #CybotCookiebotDialog,
                            .CookieDeclaration,
                            #CybotCookiebotDialogBodyUnderlay {
                                display: none !important;
                            }
                        `;
                        document.head.appendChild(style);
                    }""")

                    base_filename = f"team_info_{team_id}_{int(time.time())}"
                    image_paths = []
                    total_height = 0

                    # 1. bodyshot-team-bg (664x134)
                    bodyshot_path = os.path.join(self.screenshot_dir, f"{base_filename}_bodyshot.png")
                    bodyshot = await page.query_selector(".bodyshot-team-bg")
                    if bodyshot:
                        await bodyshot.screenshot(path=bodyshot_path)
                        image_paths.append((bodyshot_path, 134))
                        total_height += 134

                    # 2. profileTopBox (664x187)
                    profile_path = os.path.join(self.screenshot_dir, f"{base_filename}_profile.png")
                    profile = await page.query_selector(".standard-box.profileTopBox.clearfix")
                    if profile:
                        await profile.screenshot(path=profile_path)
                        image_paths.append((profile_path, 187))
                        total_height += 187

                    # 3. trophySection (664x59)
                    trophy_path = os.path.join(self.screenshot_dir, f"{base_filename}_trophy.png")
                    trophy = await page.query_selector(".trophySection")
                    if trophy:
                        await trophy.screenshot(path=trophy_path)
                        image_paths.append((trophy_path, 59))
                        total_height += 59

                    # 合并图片
                    width = 664  # 修改固定宽度为664
                    merged_image = PILImage.new('RGB', (width, total_height), 'white')
                    current_height = 0

                    # 打印日志以跟踪进度
                    self.logger.info(f"准备合并图片，总高度: {total_height}px")
                    self.logger.info(f"图片列表: {image_paths}")

                    # 合并图片
                    for idx, (img_path, height) in enumerate(image_paths, 1):
                        try:
                            with PILImage.open(img_path) as img:
                                self.logger.info(f"处理第 {idx} 张图片: {img_path}")
                                img_width, img_height = img.size
                                scale_factor = width / img_width
                                new_height = int(img_height * scale_factor)
                                resized_img = img.resize((width, new_height), PILImage.Resampling.LANCZOS)
                                merged_image.paste(resized_img, (0, current_height))
                                current_height += new_height
                                self.logger.info(f"已合并第 {idx} 张图片，当前高度: {current_height}px")
                        except Exception as e:
                            self.logger.error(f"处理图片 {img_path} 时出错: {str(e)}")

                    # 保存合并后的图片
                    merged_path = os.path.join(self.screenshot_dir, f"{base_filename}_merged.png")
                    merged_image.save(merged_path)

                    # 发送结果
                    message_chain = [
                        Plain(text=f"📊 {team_name} 战队统计数据：\n"),
                        Image(file=merged_path)
                    ]
                    yield event.chain_result(message_chain)

                    # 清理临时文件
                    for img_path, _ in image_paths:
                        try:
                            os.remove(img_path)
                        except Exception as e:
                            self.logger.debug(f"删除临时文件失败: {str(e)}")

                except Exception as e:
                    self.logger.error(f"截图过程中出错: {str(e)}")
                    yield event.plain_result("❌ 获取战队统计数据失败，请稍后重试")
                
                finally:
                    await page.close()
                    await context.close()
                    await browser.close()
            
        except Exception as e:
            self.logger.error(f"查询战队信息时发生未知错误: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            yield event.plain_result("❌ 查询战队信息失败，请稍后重试")

    @filter.command("近期比赛")
    async def query_matches(self, event: AstrMessageEvent):
        """查询HLTV近期比赛"""
        yield event.plain_result("🔍 正在查询近期比赛信息...")
        
        try:
            matches = await self.get_parsed_page("https://www.hltv.org/matches/")
            if not matches:
                self.logger.error("获取比赛页面失败")
                yield event.plain_result("❌ 获取比赛信息失败")
                return
                
            result_text = "📅 HLTV近期比赛\n" + "═" * 30 + "\n"
            match_count = 0  # 用于计数已处理的比赛数
            
            match_sections = matches.find_all("div", {"class": "upcomingMatchesSection"})
            self.logger.debug(f"找到 {len(match_sections)} 个比赛日期区块")
            
            for match_day in match_sections:
                try:
                    if (match_count >= 10):  # 如果已经处理了10场比赛，就跳出循环
                        break
                        
                    date_element = match_day.find('div', {'class': 'matchDayHeadline'})
                    if not date_element:
                        self.logger.warning("未找到比赛日期元素")
                        continue
                        
                    date = date_element.text.split()[-1]
                    self.logger.debug(f"处理日期: {date}")
                    result_text += f"\n📆 {date}:\n" + "─" * 20 + "\n"
                    
                    day_matches = match_day.find_all("div", {"class": "upcomingMatch"})
                    self.logger.debug(f"该日期下找到 {len(day_matches)} 场比赛")
                    
                    for match in day_matches:
                        if (match_count >= 10):  # 如果已经处理了10场比赛，就跳出内层循环
                            break
                            
                        try:
                            teams = match.find_all("div", {"class": "matchTeam"})
                            if len(teams) < 2:
                                self.logger.warning(f"比赛队伍数量不足: {len(teams)}")
                                continue
                                
                            team1 = teams[0].text.strip()
                            team2 = teams[1].text.strip()
                            
                            time_element = match.find("div", {"class": "matchTime"})
                            time = time_element.text if time_element else "TBA"
                            
                            event_element = match.find("div", {"class": "matchEvent"})
                            event_name = event_element.text.strip() if event_element else "Unknown Event"
                            
                            self.logger.debug(f"处理比赛: {team1} vs {team2}")
                            result_text += f"⚔️ {team1} vs {team2}\n"
                            result_text += f"⏰ {time}\n"
                            result_text += f"🏆 {event_name}\n"
                            result_text += "─" * 15 + "\n"
                            
                            match_count += 1  # 增加计数器
                            
                        except Exception as match_error:
                            self.logger.error(f"处理单场比赛时出错: {str(match_error)}")
                            self.logger.debug("比赛HTML内容:", exc_info=True)
                            continue
                            
                except Exception as day_error:
                    self.logger.error(f"处理比赛日期区块时出错: {str(day_error)}")
                    self.logger.debug("日期区块HTML内容:", exc_info=True)
                    continue
                    
            if result_text == "📅 HLTV近期比赛\n" + "═" * 30 + "\n":
                self.logger.error("未找到任何比赛信息")
                yield event.plain_result("❌ 未找到任何比赛信息")
            else:
                result_text += f"\n💡 仅显示最近 {match_count} 场比赛"  # 添加提示信息
                yield event.plain_result(result_text)
                
        except Exception as e:
            self.logger.error(f"查询比赛信息时发生错误: {str(e)}")
            self.logger.debug("完整错误信息:", exc_info=True)
            self.logger.debug("页面HTML内容:", exc_info=True)
            yield event.plain_result(f"❌ 查询失败: {str(e)}")

    async def get_match_stats(self, match_url: str):
        """获取比赛详细统计信息"""
        try:
            page = await self.get_parsed_page(f"https://www.hltv.org{match_url}")
            if not page:
                return None
                
            match_stats = {
                'team1': {'name': '', 'players': []},
                'team2': {'name': '', 'players': []},
                'maps': [],
                'event': ''
            }
            
            # 获取队伍名称
            team_names = page.find_all("div", {"class": "team"})
            if len(team_names) >= 2:
                match_stats['team1']['name'] = team_names[0].text.strip()
                match_stats['team2']['name'] = team_names[1].text.strip()
            
            # 获取比赛地图信息
            maps = page.find_all("div", {"class": "mapname"})
            for map_div in maps:
                match_stats['maps'].append(map_div.text.strip())
            
            # 获取选手数据
            stats_tables = page.find_all("table", {"class": "stats-table"})
            
            if not stats_tables:
                self.logger.warning(
                    "未找到比赛统计表格，可能比赛尚未结束或数据未更新。请检查比赛是否已结束，或稍后再试。"
                    f" URL: {match_url}, 页面内容: {page.prettify()[:500]}..."
                )
                match_stats['status'] = "比赛数据暂未更新"
                return match_stats
            
            for team_idx, team_box in enumerate(['team1', 'team2']):
                if team_idx >= len(stats_tables):
                    self.logger.warning(f"未找到第{team_idx + 1}支队伍的统计表格")
                    continue
                    
                try:
                    rows = stats_tables[team_idx].find_all("tr")
                    if len(rows) <= 1:  # 跳过表头
                        continue
                        
                    for player_row in rows[1:]:  # 从第二行开始是选手数据
                        stats = player_row.find_all("td")
                        if len(stats) >= 6:  # 确保至少有足够的列
                            player_info = {
                                'name': stats[0].text.strip(),
                                'kills': stats[1].text.strip() if len(stats) > 1 else 'N/A',
                                'deaths': stats[2].text.strip() if len(stats) > 2 else 'N/A',
                                'adr': stats[3].text.strip() if len(stats) > 3 else 'N/A',
                                'kast': stats[4].text.strip() if len(stats) > 4 else 'N/A',
                                'rating': stats[5].text.strip() if len(stats) > 5 else 'N/A'
                            }
                            match_stats[team_box]['players'].append(player_info)
                except Exception as e:
                    self.logger.error(f"处理{team_box}统计数据时出错: {str(e)}")
                    continue
            
            # 获取赛事信息
            event = page.find("div", {"class": "event"})
            if event:
                match_stats['event'] = event.text.strip()
            
            return match_stats
        except Exception as e:
            self.logger.error(f"获取比赛统计信息失败: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            return None

    @filter.command("比赛结果")
    async def query_results(self, event: AstrMessageEvent):
        """查询HLTV最近比赛结果"""
        yield event.plain_result("🔍 正在查询近期比赛结果...")
        
        try:
            results = await self.get_parsed_page("https://www.hltv.org/results/")
            result_text = "📊 HLTV近期比赛结果\n" + "═" * 30 + "\n\n"
            
            # 清理之前的比赛信息
            self.recent_matches.clear()
            self.logger.debug("已清理之前的比赛记录")
            
            # 只获取前5场比赛
            for idx, result in enumerate(results.find_all("div", {"class": "result-con"})[:5], 1):
                if result.find_all("td", {"class": "team-cell"}):
                    team1 = result.find_all("td", {"class": "team-cell"})[0].text.strip()
                    team2 = result.find_all("td", {"class": "team-cell"})[1].text.strip()
                    score1 = result.find("td", {"class": "result-score"}).find_all("span")[0].text.strip()
                    score2 = result.find("td", {"class": "result-score"}).find_all("span")[1].text.strip()
                    event_name = result.find("td", {"class": "event"}).text if result.find("td", {"class": "event"}) else "Unknown Event"
                    
                    # 获取并存储比赛URL
                    match_link = result.find("a", {"class": "a-reset"})
                    if match_link and 'href' in match_link.attrs:
                        match_url = match_link['href']
                        # 使用字母作为键 (idx从1开始,所以要-1)
                        letter = chr(ord('a') + idx - 1)  # 将数字转换为对应字母
                        self.recent_matches[letter] = match_url
                        self.logger.debug(f"存储比赛记录: {letter} -> {match_url}")
                    
                    result_text += f"📍 比赛 {chr(ord('a') + idx - 1)}\n"
                    result_text += f"⚔️ {team1} vs {team2}\n"
                    result_text += f"📈 比分: {score1} - {score2}\n"
                    result_text += f"🏆 赛事: {event_name}\n"
                    result_text += "─" * 20 + "\n"
            
            result_text += "\n💡 在30秒内输入字母(a-e)可查看详细数据"
            
            # 记录查询时间和用户ID
            user_id = event.get_session_id()
            self.last_result_query[user_id] = time.time()
            self.logger.debug(f"用户 {user_id} 的查询时间已更新")
            
            yield event.plain_result(result_text)
            
        except Exception as e:
            yield event.plain_result(f"❌ 查询失败: {str(e)}")

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """清理浏览器资源"""
        if self.team_map:
            self.team_map.clear()

    async def get_top_players(self):
        """获取HLTV TOP选手信息"""
        try:
            self.logger.info("正在获取TOP选手信息...")
            page = await self.get_parsed_page("https://www.hltv.org/stats")
            if not page:
                self.logger.error("获取TOP选手页面失败")
                return []
                
            players_div = page.find_all("div", {"class": "col"})[0]
            players = []
            
            for player in players_div.find_all("div", {"class": "top-x-box standard-box"}):
                try:
                    player_info = {
                        'country': player.find_all('img')[1]['alt'],
                        'name': player.find('img', {'class': 'img'})['alt'].split("'")[0].rstrip() + 
                               player.find('img', {'class': 'img'})['alt'].split("'")[2],
                        'nickname': player.find('a', {'class': 'name'}).text,
                        'rating': player.find('div', {'class': 'rating'}).find('span', {'class': 'bold'}).text,
                        'maps_played': player.find('div', {'class': 'average gtSmartphone-only'}).find('span', {'class': 'bold'}).text,
                        'url': "https://hltv.org" + player.find('a', {'class': 'name'}).get('href'),
                        'id': int(player.find('a', {'class': 'name'}).get('href').split("/")[-2])
                    }
                    players.append(player_info)
                    self.logger.debug(f"添加选手: {player_info['nickname']} ({player_info['name']})")
                except Exception as e:
                    self.logger.error(f"解析选手信息时出错: {str(e)}")
                    continue
                    
            return players
            
        except Exception as e:
            self.logger.error(f"获取TOP选手信息失败: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            return []

    
    @filter.command("搜索选手", parse_flags=False)
    async def search_player_by_name(self, event: AstrMessageEvent):
        """通过名字搜索选手"""
        message = event.message_obj.message_str
        # 使用空格分割，但只分割第一个空格
        parts = message.split(' ', 1)
        if len(parts) != 2:
            yield event.plain_result("❌ 请输入要搜索的选手名称")
            return
            
        player_name = parts[1].strip()  # 直接获取第二部分作为选手名称
        if not player_name:
            yield event.plain_result("❌ 请输入要搜索的选手名称")
            return
            
        yield event.plain_result(f"🔍 正在搜索选手: {player_name}，请稍候...")
        # ... 其余代码保持不变 ...
        
        try:
            players = await self.search_players(player_name)
            
            if not players:
                yield event.plain_result(f"❌ 未找到包含 '{player_name}' 的选手")
                return
                
            result = "🔍 搜索结果:\n" + "═" * 30 + "\n\n"
            
            # 存储搜索结果和时间
            user_id = event.get_session_id()
            self.player_search_results[user_id] = players[:5]  # 只保存前5个结果
            self.last_search_time[user_id] = time.time()
            
            for idx, player in enumerate(players[:5], 1):
                result += f"#{idx} {player['nickname']}\n"
                result += f"🌍 国籍: {player['country']}\n"
                result += f"🆔 ID: {player['id']}\n"
                result += "─" * 20 + "\n"
                
            if len(players) > 5:
                result += f"\n💡 找到更多结果，只显示前5个匹配项"
                
            result += "\n📌 在30秒内输入序号(1-5)可查看选手详细数据"
                
            yield event.plain_result(result)
            
        except Exception as e:
            self.logger.error(f"搜索选手失败: {str(e)}")
            yield event.plain_result("❌ 搜索选手失败，请稍后重试")

    @filter.regex(r"^[1-5]$")
    async def handle_player_stats(self, event: AstrMessageEvent):
        """处理选手详细统计信息查询"""
        try:
            user_id = event.get_session_id()
            current_time = time.time()
            
            # 检查是否在30秒内发起的选手搜索查询
            if user_id not in self.last_search_time or \
               current_time - self.last_search_time[user_id] > 30 or \
               user_id not in self.player_search_results:
                # 转发到比赛详情处理
                async for result in self.handle_match_details(event):
                    yield result
                return
            
            # 获取选择的序号
            messages = event.get_messages()
            if not messages:
                return
            
            selected_index = int(messages[0].text.strip()) - 1
            selected_player = self.player_search_results[user_id][selected_index]
            
            # 使用nickname替代name
            yield event.plain_result(f"📊 正在获取 {selected_player['nickname']} 的详细数据，请稍候...")
            
            # 使用playwright访问选手统计页面并截图
            async with async_playwright() as playwright:
                browser = None
                context = None
                page = None
                
                try:
                    browser = await playwright.chromium.launch(
                        headless=True,
                        args=[
                            '--disable-web-security',
                            '--disable-features=IsolateOrigins,site-per-process',
                            '--no-sandbox',
                            '--disable-setuid-sandbox',
                            '--disable-dev-shm-usage',
                        ]
                    )
                    
                    # 更新上下文配置
                    context = await browser.new_context(
                        viewport={'width': 1920, 'height': 1080},
                        user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
                        ignore_https_errors=True,
                        # 添加以下cookie设置
                        accept_downloads=True,
                        java_script_enabled=True,
                        bypass_csp=True,
                        permissions=['notifications', 'geolocation'],
                        # 允许所有cookies
                        extra_http_headers={
                            'Accept': '*/*',
                            'Accept-Language': 'en-US,en;q=0.9',
                            'Accept-Encoding': 'gzip, deflate, br',
                        }
                    )

                    page = await context.new_page()
                    
                    # 添加cookie同意
                    await page.add_init_script("""
                        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                        window.localStorage.setItem('CookieConsent', JSON.stringify({
                            accepted: true,
                            necessary: true,
                            preferences: true,
                            statistics: true,
                            marketing: true
                        }));
                    """)

                    # 添加重试机制
                    max_retries = 3
                    retry_delay = 2
                    
                    for attempt in range(max_retries):
                        try:
                            url = f"https://www.hltv.org/stats/players/{selected_player['id']}/{selected_player['nickname']}"
                            self.logger.info(f"第 {attempt + 1} 次尝试访问URL: {url}")
                            
                            page.set_default_timeout(45000)  # 45秒超时
                            response = await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                            
                            if response.status == 403:
                                self.logger.warning("收到403响应，等待后重试")
                                await asyncio.sleep(retry_delay * (attempt + 1))
                                continue
                                
                            await page.wait_for_load_state("networkidle", timeout=45000)
                            
                            # 延迟等待确保页面加载完成
                            await asyncio.sleep(3)
                            
                            # 在选手统计页面加载后,截图前添加以隐藏cookie窗口的脚本
                            await page.evaluate("""() => {
                                // 使用CSS隐藏cookiebot相关元素
                                const style = document.createElement('style');
                                style.textContent = `
                                    #CybotCookiebotDialog,
                                    .CookieDeclaration,
                                    #CybotCookiebotDialogBodyUnderlay,
                                    .cookiebot-overlay,
                                    [class*="cookie-notice"],
                                    [class*="cookie-banner"],
                                    [id*="cookie-banner"],
                                    [id*="cookie-notice"] {
                                        display: none !important;
                                        visibility: hidden !important;
                                        opacity: 0 !important;
                                        z-index: -9999 !important;
                                    }
                                `;
                                document.head.appendChild(style);
                            }""")
                            # 生成基础截图文件名
                            base_filename = f"player_stats_{selected_player['id']}_{int(time.time())}"
                            image_paths = []
                            total_height = 0
                            width = 648  # 固定宽度
                            
                            # 获取并截取三个统计区域
                            # 1. playerSummaryStatBox
                            summary_element = await page.wait_for_selector(".playerSummaryStatBox", timeout=45000)
                            if summary_element:
                                summary_path = os.path.join(self.screenshot_dir, f"{base_filename}_summary.png")
                                await summary_element.screenshot(path=summary_path)
                                image_paths.append((summary_path, 245))
                                total_height += 245
                            
                            # 2. role-stats-container
                            role_stats_element = await page.wait_for_selector(".role-stats-container.standard-box", timeout=45000)
                            if role_stats_element:
                                role_stats_path = os.path.join(self.screenshot_dir, f"{base_filename}_role_stats.png")
                                await role_stats_element.screenshot(path=role_stats_path)
                                image_paths.append((role_stats_path, 305))
                                total_height += 305
                            
                            # 3. 选手详细数据
                            stats_path = os.path.join(self.screenshot_dir, f"{base_filename}_stats.png")
                            spoiler_element = await page.query_selector(".statistics")
                            if spoiler_element:
                                await spoiler_element.screenshot(path=stats_path)
                                image_paths.append((stats_path, 248))
                                total_height += 248
                                self.logger.info("成功截取选手详细数据(.statistics)")
                            else:
                                self.logger.warning("未找到选手详细数据元素(.statistics)")

                            if not image_paths:
                                raise Exception("未能成功截取任何统计数据区域")

                            # 创建合并后的图片
                            merged_image = PILImage.new('RGB', (width, total_height), 'white')
                            current_height = 0

                            # 依次粘贴每张图片
                            for img_path, target_height in image_paths:
                                with PILImage.open(img_path) as img:
                                    # 调整图片大小以匹配目标宽度
                                    img_width, img_height = img.size
                                    scale_factor = width / img_width
                                    new_height = int(img_height * scale_factor)
                                    resized_img = img.resize((width, new_height), PILImage.Resampling.LANCZOS)
                                    merged_image.paste(resized_img, (0, current_height))
                                    current_height += new_height

                            # 保存合并后的图片
                            merged_path = os.path.join(self.screenshot_dir, f"{base_filename}_merged.png")
                            merged_image.save(merged_path)

                            # 发送结果
                            message_chain = [
                                Plain(text=f"📊 {selected_player['nickname']} 的统计数据：\n"),
                                Image(file=merged_path)
                            ]
                            yield event.chain_result(message_chain)

                            # 清理临时文件
                            for img_path, _ in image_paths:
                                try:
                                    os.remove(img_path)
                                except Exception as e:
                                    self.logger.debug(f"删除临时文件失败: {str(e)}")

                            break  # 如果成功则跳出重试循环
                            
                        except Exception as e:
                            if attempt == max_retries - 1:  # 最后一次尝试失败
                                raise e
                            self.logger.warning(f"第 {attempt + 1} 次尝试失败: {str(e)}")
                            await asyncio.sleep(retry_delay * (attempt + 1))
                    
                except Exception as e:
                    self.logger.error(f"截图过程中出错: {str(e)}")
                    yield event.plain_result("❌ 获取统计数据失败，请稍后重试")
                    
                finally:
                    # 清理资源
                    if page:
                        await page.close()
                    if context:
                        await context.close()
                    if browser:
                        await browser.close()
                    
        except Exception as e:
            self.logger.error(f"获取选手统计信息失败: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            yield event.plain_result("❌ 获取选手统计信息失败，请稍后重试")

    @filter.command("top选手")
    async def query_top_players(self, event: AstrMessageEvent):
        """查询HLTV TOP选手排名"""
        yield event.plain_result("🔍 正在查询HLTV TOP选手排名，请稍候...")
        
        try:
            players = await self.get_top_players()
            
            if not players:
                yield event.plain_result("❌ 获取选手排名失败，请稍后重试")
                return
                
            result = "🏆 HLTV TOP选手排名 🏆\n" + "═" * 30 + "\n\n"
            
            for idx, player in enumerate(players[:10], 1):
                result += f"{'🥇' if idx == 1 else '🥈' if idx == 2 else '🥉' if idx == 3 else '🏅'} #{idx} {player['nickname']}\n"
                result += f"👤 {player['name']} | 🌍 {player['country']}\n"
                result += f"📊 评分: {player['rating']} | 🗺️ 地图数: {player['maps_played']}\n"
                result += "─" * 25 + "\n"
                
            yield event.plain_result(result)
            
        except Exception as e:
            self.logger.error(f"查询TOP选手失败: {str(e)}")
            yield event.plain_result("❌ 查询选手排名失败，请稍后重试")

    @filter.command("选手详情")
    async def query_player_details(self, event: AstrMessageEvent, *, player_id: str):
        """查询指定选手ID的详细信息"""
        yield event.plain_result(f"🔍 正在查询选手ID {player_id} 的详细信息，请稍候...")
        
        try:
            player_info = await self.get_player_info(player_id)
            
            if not player_info:
                yield event.plain_result(f"❌ 未找到ID为 {player_id} 的选手信息")
                return
                
            result = "👤 选手详细信息:\n" + "═" * 30 + "\n\n"
            
            # 添加基本信息
            result += f"📝 昵称: {player_info.get('nickname', 'N/A')}\n"
            result += f"👤 姓名: {player_info.get('name', 'N/A')}\n"
            if 'team' in player_info:
                result += f"🏢 所属战队: {player_info['team']}\n"
            if 'country' in player_info:
                result += f"🌍 国籍: {player_info['country']}\n"
            result += "\n"
            
            # 添加统计数据
            result += "📊 数据统计:\n" + "─" * 20 + "\n"
            for key, value in player_info.items():
                if key not in ['nickname', 'name', 'team', 'country']:
                    result += f"• {key}: {value}\n"
                    
            yield event.plain_result(result)
            
        except Exception as e:
            self.logger.error(f"查询选手详细信息失败: {str(e)}")
            yield event.plain_result("❌ 查询选手详细信息失败，请稍后重试")

    @filter.regex(r"^[a-e]$")  # 保持原有的a-e匹配
    async def handle_match_details(self, event: AstrMessageEvent):
        """处理比赛详细信息查询"""
        try:
            user_id = event.get_session_id()
            current_time = time.time()
            
            # 获取用户输入的字母
            selected_letter = event.get_messages()[0].text.strip().lower()
            
            # 检查是否在30秒内发起的比赛结果查询
            if user_id not in self.last_result_query or \
               current_time - self.last_result_query[user_id] > 30:
                self.logger.debug(f"用户 {user_id} 的查询已超时或未找到查询记录")
                return
            
            # 检查输入的字母是否存在对应的比赛URL
            if selected_letter not in self.recent_matches:
                self.logger.debug(f"未找到字母 {selected_letter} 对应的比赛记录")
                return
                
            # 获取对应的比赛URL
            match_url = self.recent_matches[selected_letter]
            self.logger.info(f"正在获取比赛详情，URL: {match_url}")
            yield event.plain_result("📊 正在获取比赛详细数据，请稍候...")

            async with async_playwright() as playwright:
                browser = await playwright.chromium.launch(
                    headless=True,
                    args=[
                        '--disable-web-security',
                        '--disable-features=IsolateOrigins,site-per-process',
                        '--no-sandbox',
                        '--disable-setuid-sandbox',
                        '--disable-dev-shm-usage',
                    ]
                )
                
                # 更新上下文配置
                context = await browser.new_context(
                    viewport={'width': 1920, 'height': 1080},
                    user_agent='Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0',
                    ignore_https_errors=True,
                    accept_downloads=True,
                    java_script_enabled=True,
                    bypass_csp=True,
                    permissions=['notifications', 'geolocation'],
                    extra_http_headers={
                        'Accept': '*/*',
                        'Accept-Language': 'en-US,en;q=0.9',
                        'Accept-Encoding': 'gzip, deflate, br',
                    }
                )

                page = await context.new_page()
                
                # 添加cookie同意
                await page.add_init_script("""
                    Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                    window.localStorage.setItem('CookieConsent', JSON.stringify({
                        accepted: true,
                        necessary: true,
                        preferences: true,
                        statistics: true,
                        marketing: true
                    }));
                """)

                try:
                    url = f"https://www.hltv.org{match_url}"
                    page.set_default_timeout(45000)  # 45秒超时
                    await page.goto(url, wait_until="domcontentloaded", timeout=45000)
                    await page.wait_for_load_state("networkidle", timeout=45000)
                    
                    # 延迟等待确保页面加载完成
                    await asyncio.sleep(3)
                    
                    # 页面加载后,截图前的代码
                    await page.evaluate("""() => {
                        // 使用CSS隐藏cookiebot相关元素
                        const style = document.createElement('style');
                        style.textContent = `
                            #CybotCookiebotDialog,
                            .CookieDeclaration,
                            #CybotCookiebotDialogBodyUnderlay,
                            .cookiebot-overlay,
                            [class*="cookie-notice"],
                            [class*="cookie-banner"],
                            [id*="cookie-banner"],
                            [id*="cookie-notice"] {
                                display: none !important;
                                visibility: hidden !important;
                                opacity: 0 !important;
                                z-index: -9999 !重要;
                            }
                        `;
                        document.head.appendChild(style);
                    }""")
                    
                    # 生成基础截图文件名
                    base_filename = f"match_details_{int(time.time())}"
                    
                    # 首先添加一个通用的截图函数
                    async def screenshot_element(page, selector, file_path, timeout=45000):
                        try:
                            element = await page.wait_for_selector(selector, timeout=timeout)
                            if element:
                                await element.screenshot(path=file_path)
                                return True
                        except Exception as e:
                            self.logger.warning(f"截取元素 {selector} 失败: {str(e)}")
                        return False

                    # 在handle_match_details方法中的截图部分替换为:
                    image_paths = []
                    total_height = 0

                   # 在handle_match_details方法中:
                    image_paths = []
                    total_height = 0

                    #1. 大比分
                    teams_path = os.path.join(self.screenshot_dir, f"{base_filename}_teams.png")
                    if await screenshot_element(page, ".standard-box.teamsBox", teams_path):
                         image_paths.append((teams_path, 300))
                         total_height += 300

                    #2. 地图比分 
                    score_path = os.path.join(self.screenshot_dir, f"{base_filename}_score.png")
                    score_element = await page.query_selector(".flexbox-column")
                    if score_element:
                         await score_element.screenshot(path=score_path)
                         image_paths.append((score_path, 200))
                         total_height += 200
                            
                    # 3. 比赛数据统计
                    stats_path = os.path.join(self.screenshot_dir, f"{base_filename}_stats.png")
                    stats_element = await page.query_selector("div#all-content.stats-content")
                    if stats_element:
                        # 获取元素的实际高度
                        bbox = await stats_element.bounding_box()
                        if bbox:
                            actual_height = int(bbox['height'])
                            # 为了确保完整截图，将高度设置得更大一些
                            await stats_element.screenshot(path=stats_path)
                            image_paths.append((stats_path, actual_height+220)) 
                            total_height += actual_height+220
                            self.logger.info(f"成功截取比赛数据(div#all-content.stats-content), 实际高度: {actual_height}px")
                        else:
                            self.logger.warning("无法获取比赛数据元素的边界框")
                    else:
                        self.logger.warning("未找到比赛数据元素(div#all-content.stats-content)")

                    # 检查是否至少有一个截图成功
                    if not image_paths:
                        self.logger.error("未能成功截取任何比赛数据")
                        yield event.plain_result("❌ 获取比赛详情失败，未能找到相关数据")
                        return
                    
                    # 合并图片
                    width = 645  # 固定宽度
                    current_height = 0

                    # 首先计算实际需要的总高度
                    total_height = 0
                    for _, img_height in image_paths:
                        with PILImage.open(_) as img:
                            img_width, img_height = img.size
                            scale_factor = width / img_width
                            new_height = int(img_height * scale_factor)
                            total_height += new_height

                    # 创建足够大的画布
                    merged_image = PILImage.new('RGB', (width, total_height), 'white')

                    # 依次粘贴图片
                    for img_path, _ in image_paths:
                        try:
                            with PILImage.open(img_path) as img:
                                # 调整图片大小以匹配目标宽度
                                img_width, img_height = img.size
                                scale_factor = width / img_width
                                new_height = int(img_height * scale_factor)
                                resized_img = img.resize((width, new_height), PILImage.Resampling.LANCZOS)
                                
                                # 确保不会超出边界
                                if current_height + new_height <= total_height:
                                    merged_image.paste(resized_img, (0, current_height))
                                    current_height += new_height
                                    
                        except Exception as e:
                            self.logger.error(f"处理图片 {img_path} 时出错: {str(e)}")
                    
                    # 保存合并后的图片
                    merged_path = os.path.join(self.screenshot_dir, f"{base_filename}_merged.png")
                    merged_image.save(merged_path)
                    
                    # 发送结果
                    message_chain = [
                        Plain(text="📊 比赛详细数据：\n"),
                        Image(file=merged_path)
                    ]
                    yield event.chain_result(message_chain)
                    
                    # 清理临时文件
                    for img_path, _ in image_paths:
                        try:
                            os.remove(img_path)
                        except Exception as e:
                            self.logger.debug(f"删除临时文件失败: {str(e)}")
                    
                except Exception as e:
                    self.logger.error(f"获取比赛详情失败: {str(e)}")
                    yield event.plain_result("❌ 获取比赛详情失败，请稍后重试")
                
                finally:
                    await page.close()
                    await context.close()
                    await browser.close()
                    
        except Exception as e:
            self.logger.error(f"处理比赛详情查询失败: {str(e)}")
            yield event.plain_result("❌ 获取比赛详情失败，请稍后重试")

            # 在handle_match_details方法中修改图片合并部分的代码：

            # 在截图部分后添加日志记录
            self.logger.info(f"准备合并的图片路径: {image_paths}")
            self.logger.info(f"计算得到的总高度: {total_height}")

            # 合并图片部分的代码修改如下
            try:
                width = 1000  # 固定宽度
                merged_image = PILImage.new('RGB', (width, total_height), 'white')
                current_height = 0
                
                for img_path, target_height in image_paths:
                    self.logger.info(f"正在处理图片: {img_path}, 目标高度: {target_height}")
                    try:
                        with PILImage.open(img_path) as img:
                            # 记录原始图片尺寸
                            original_size = img.size
                            self.logger.info(f"原始图片尺寸: {original_size}")
                            
                            # 调整图片大小以匹配目标宽度
                            img_width, img_height = img.size
                            scale_factor = width / img_width
                            new_height = int(img_height * scale_factor)
                            self.logger.info(f"缩放后的新高度: {new_height}")
                            
                            resized_img = img.resize((width, new_height), PILImage.Resampling.LANCZOS)
                            merged_image.paste(resized_img, (0, current_height))
                            self.logger.info(f"已粘贴图片到位置: y={current_height}")
                            
                            current_height += new_height
                            self.logger.info(f"当前累计高度: {current_height}")
                            
                    except Exception as e:
                        self.logger.error(f"处理图片 {img_path} 时出错: {str(e)}")

                # 记录最终合并图片的尺寸
                self.logger.info(f"最终合并图片尺寸: {merged_image.size}")
                
                # 保存合并后的图片
                merged_path = os.path.join(self.screenshot_dir, f"{base_filename}_merged.png")
                merged_image.save(merged_path)
                self.logger.info(f"已保存合并图片到: {merged_path}")
                
            except Exception as e:
                self.logger.error(f"合并图片时发生错误: {str(e)}")
                raise e

    async def search_players(self, player_name: str):
        """搜索选手信息"""
        try:
            self.logger.info(f"正在搜索选手: {player_name}")
            url = f"https://www.hltv.org/search?query={player_name}"
            page = await self.get_parsed_page(url)
            
            if not page:
                return []
                
            players = []
            # 找到第一个table元素
            width_control = page.find("div", {"class": "widthControl"})
            if not width_control:
                self.logger.error("未找到widthControl元素")
                return []
                
            first_table = width_control.find("table")
            if not first_table:
                self.logger.error("未找到table元素")
                return []
                
            # 遍历table下的所有行
            for row in first_table.find_all("tr"):
                try:
                    # 获取选手链接
                    player_link = row.find("a")
                    if not player_link:
                        continue
                        
                    # 提取选手URL和ID
                    player_url = player_link.get("href", "")
                    if not player_url.startswith("/player/"):
                        continue
                        
                    # 解析URL获取选手ID和名称
                    _, _, player_id, player_nickname = player_url.split("/")
                    
                    # 获取国籍 (从img标签的alt属性)
                    country_img = row.find("img", {"class": "flag"})
                    country = country_img.get("alt", "Unknown") if country_img else "Unknown"
                    
                    # 构建详细页URL
                    stats_url = f"https://www.hltv.org/stats/players/{player_id}/{player_nickname}"
                    
                    player_info = {
                        'id': int(player_id),
                        'nickname': player_nickname,
                        'country': country,
                        'url': stats_url
                    }
                    players.append(player_info)
                    
                    self.logger.debug(f"找到选手: {player_info}")
                    
                except Exception as e:
                    self.logger.error(f"解析选手信息时出错: {str(e)}")
                    continue
                    
            return players
            
        except Exception as e:
            self.logger.error(f"搜索选手失败: {str(e)}")
            self.logger.debug("异常详情: ", exc_info=True)
            return []
