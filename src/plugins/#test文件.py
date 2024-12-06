from typing import Union, Optional, List, Any
import datetime
import asyncio
import nonebot
from nonebot.rule import Rule
from nonebot import require, get_driver, get_bot
from nonebot import on_command, on_startswith, on_keyword, on_fullmatch, on_message, on_request
from nonebot.matcher import Matcher
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PrivateMessageEvent, FriendRequestEvent, \
    GroupRequestEvent
from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER, GROUP_MEMBER
from nonebot.permission import SUPERUSER
from nonebot.typing import T_State
from nonebot.log import logger
from nonebot.params import ArgPlainText, CommandArg, ArgStr
from nonebot.adapters.onebot.v11 import Bot, GroupIncreaseNoticeEvent, \
    MessageSegment, Message, GroupMessageEvent, Event, escape, ActionFailed
import os
import random
from pathlib import Path
from typing import Dict, List, Optional, Tuple
from nonebot.plugin import on_regex
from nonebot.params import Matcher, RegexGroup
import aiofiles
import asyncio
import re

from langchain_openai import ChatOpenAI
from nonebot.rule import to_me
from langchain_core.messages import AnyMessage, SystemMessage, HumanMessage, ToolMessage
try:
    #ujson由c语言编写，速度上有优势
    import ujson as json
except ImportError:
    import json

#-------------------------路径json声明---------------------------
#配置路径
config_path = Path("config/number.json")
#关于路径的一些操作
config_path.parent.mkdir(parents=True, exist_ok=True)
#若配置json文件存在则直接打开并写入
if config_path.exists():
    with open(config_path, "r", encoding="utf8") as f:
        #字典加载json文件
        CONFIG: Dict[str, List] = json.load(f)
#不存在则创建并写入默认配置
else:
    CONFIG: Dict[str, List] = {"opened_groups": [],"unfinished_number":[],"finished_number":[]}
    with open(config_path, "w", encoding="utf8") as f:
        json.dump(CONFIG, f, ensure_ascii=False, indent=4)
#----------------------每日任务记录路径----------------------------
config_path2 = Path("config/log.json")
if config_path2.exists():
    with open(config_path2, "r", encoding="utf8") as f:
        #字典加载json文件
        CONFIG2: Dict[str, Any] = json.load(f)
#不存在则创建并写入默认配置
else:
    CONFIG2: Dict[str, Any] = {}
    with open(config_path2, "w", encoding="utf8") as f:
        json.dump(CONFIG2, f, ensure_ascii=False, indent=4)
#-------------------------定时任务准备-----------------------------
try:
    scheduler = require("nonebot_plugin_apscheduler").scheduler
except Exception:
    os.system("pip install -i https://pypi.tuna.tsinghua.edu.cn/simple/ nonebot_plugin_apscheduler")
    logger.warning("请重启程序！")
    scheduler = None

logger.opt(colors=True).info(
    "已检测到软依赖<y>nonebot_plugin_apscheduler</y>, <g>开启定时任务功能</g>"
    if scheduler
    else "未检测到软依赖<y>nonebot_plugin_apscheduler</y>，<r>定时任务功能未启用</r>"
)
lock = asyncio.Lock()
#-------------------------编写一个写入模块-----------------------
async def write_config():
    async with lock:
        #打开配置文件
        async with aiofiles.open(config_path, "w", encoding="utf8") as f:
            #写入配置文件
            await f.write(json.dumps(CONFIG, ensure_ascii=False, indent=4))
async def write_config2():
    async with lock:
        #打开配置文件
        async with aiofiles.open(config_path2, "w", encoding="utf8") as f:
            #写入配置文件
            await f.write(json.dumps(CONFIG2, ensure_ascii=False, indent=4))
#-------------------------开启/关闭提醒--------------------------
turn_matcher = on_regex(r"^(开启|关闭)定时提醒([0-9]*)$", priority=999)

@turn_matcher.handle()
#正则表达式获得参数开启或关闭，群号（regexgroup)
async def _(
    bot: Bot,
    event: MessageEvent,
    matcher: Matcher,
    args: Tuple[Optional[str], ...] = RegexGroup(),
):
    if not scheduler:
        await matcher.finish("未安装软依赖nonebot_plugin_apscheduler，不能使用定时发送功能")
    #开启或关闭
    mode = args[0]
    #
    if isinstance(event, GroupMessageEvent):
        group_id = args[1] if args[1] else str(event.group_id)
    else:
        if args[1]:
            group_id = args[1]
        else:
            await matcher.finish("私聊开关需要输入指定群号")
    if mode == "开启":
        if group_id in CONFIG["opened_groups"]:
            await matcher.finish("该群已经开启，无需重复开启")
        else:
            CONFIG["opened_groups"].append(group_id)
            #初始化群友
            group_users = await bot.get_group_member_list(group_id=group_id)
            #加入CONFIG中
            for member in group_users:
                if str(member['user_id']) != '3766614101' and str(member['user_id']) !='1657212058':
                    member_id = str(member['user_id'])
                    CONFIG2[member_id]= {} 
                    CONFIG["unfinished_number"].append(member_id)
                    #分别为打卡天数，未打卡天数
                    CONFIG[f"{member_id}_addup"] = [0,0]

    else:
        if group_id in CONFIG["opened_groups"]:
            CONFIG["opened_groups"].remove(group_id)
        else:
            await matcher.finish("该群尚未开启，无需关闭")
    await write_config()
    await write_config2()
    await matcher.finish(f"已成功{mode}{group_id}的提醒")

#-------------------------已打开人员从名单去除--------------------
#获取群成员id
plan = on_command('计划')

@plan.handle()
async def record_plan(bot: Bot, event: MessageEvent,matcher: Matcher):
    user = event.get_user_id()
    #从名单中去除
    if user in CONFIG["unfinished_number"]:
        CONFIG["unfinished_number"].remove(user)
        CONFIG["finished_number"].append(user)
        CONFIG[f"{user}_addup"][0]+= 1
        #未打卡天数置为0
        CONFIG[f"{user}_addup"][1] = 0
        current_datetime = datetime.datetime.now()
        day = str(current_datetime.date())
        CONFIG2[user][day] = str(event.get_message())
    await write_config()
    await write_config2()
    await matcher.finish(f"感谢完成打卡！")
#-------------------------定时提醒任务执行--------------------------
async def post_scheduler():
    bot: Bot = get_bot()
    delay = 0.5      
    for group_id in CONFIG["opened_groups"]:
        #发送消息
        for number in CONFIG["unfinished_number"]:
            msg = MessageSegment.text(f"到了打卡时间了家人")+ MessageSegment.at(int(number))
            await bot.send_group_msg(group_id=int(group_id), message=msg)
            #等待一段时间
            await asyncio.sleep(delay)
        

if scheduler:
    logger.opt(colors=True).info(
        f"已设定于 <y>{str(22).rjust(2, '0')}:{str(20).rjust(2, '0')}</y> 定时发送提醒"
    )
    scheduler.add_job(
        post_scheduler, "cron", hour=22, minute=20, id="everyday_remind"
    )
#------------------------未完成人员提醒---------------------------
async def remind():
    bot: Bot = get_bot()
    delay = 0.5
    current_datetime = datetime.datetime.now()
    weekday = current_datetime.weekday()
    #周末时间
    if weekday == 5:
        for group_id in CONFIG["opened_groups"]:
            msg = MessageSegment.text(f"周末时间，大家好好休息！")
            await bot.send_group_msg(group_id=int(group_id), message=msg)
            await asyncio.sleep(delay)
    else:
        for group_id in CONFIG["opened_groups"]:
            for number in CONFIG["unfinished_number"]:
                msg1 = MessageSegment.text(f"今日未完成打卡，已做记录！")+ MessageSegment.at(int(number))
                CONFIG[f"{number}_addup"][1] +=1
                await bot.send_group_msg(group_id=int(group_id), message=msg1)
                #等待一段时间
                await asyncio.sleep(delay)
                day_number = CONFIG[f"{number}_addup"][1]
                msg2 = MessageSegment.text(f"目前连续{day_number}天未打卡，红包金额累计至{5*day_number}元")
                await bot.send_group_msg(group_id=int(group_id), message=msg2)
                await asyncio.sleep(delay)

            for number in CONFIG["finished_number"]:
                #若完成七日打卡
                if CONFIG[f"{number}_addup"][0] == 7:
                    msg = MessageSegment.at(int(number))+MessageSegment.text(f"连续完成七天打卡，恭喜！！！")
                    #重置为0开始计数
                    CONFIG[f"{number}_addup"][0] = 0
                    await bot.send_group_msg(group_id=int(group_id), message=msg,at_all=True)


        #重置群成员
        CONFIG["finished_number"] = []
        CONFIG["unfinished_number"] = []
        group_users = await bot.get_group_member_list(group_id=group_id)
        #加入CONFIG中
        for member in group_users:
            if str(member['user_id']) != '3766614101' and str(member['user_id']) !='1657212058':
                member_id = str(member['user_id'])
                CONFIG["unfinished_number"].append(member_id)
        
        await write_config()

if scheduler:
    logger.opt(colors=True).info(
        f"已设定于 <y>{str(22).rjust(2, '0')}:{str(35).rjust(2, '0')}</y> 定时发送提醒"
    )
    scheduler.add_job(
        remind, "cron", hour=22, minute=35, id="everyday_record"
    )

#--------------------------------请假------------------------------------------
leave_tomorrow = on_command('明日请假')
@leave_tomorrow.handle()
async def record_plan(bot: Bot, event: MessageEvent,matcher: Matcher):
    user = event.get_user_id()
    #从名单中去除
    if user in CONFIG["unfinished_number"]:
        #从未打卡名单去除
        CONFIG["unfinished_number"].remove(user)
        #但同时连续重置
        CONFIG[f"{user}_addup"][0]= 0

    await write_config()
    await matcher.finish(f"已记录请假，祝好！")

leave_today = on_command('今日请假')
@leave_today.handle()
async def record_plan(bot: Bot, event: MessageEvent,matcher: Matcher):
    user = event.get_user_id()
    CONFIG[f"{user}_addup"][0]= 0

    await write_config()
    await matcher.finish(f"已记录请假，好好休息吧是（￣︶￣）↗　")

#-----------------------------操控数据内容--------------------------------------
def At(data: str) -> Union[list[str], list[int], list]:
    """
    检测at了谁，返回[qq, qq, qq,...]
    包含全体成员直接返回['all']
    如果没有at任何人，返回[]
    :param data: event.json()  event: GroupMessageEvent
    :return: list
    """
    try:
        qq_list = []
        data = json.loads(data)
        for msg in data['message']:
            if msg['type'] == 'at':
                if 'all' not in str(msg):
                    qq_list.append(int(msg['data']['qq']))
                else:
                    return ['all']
        return qq_list
    except KeyError:
        return []
#------------------------------帮助--------------------------------------------
   
#-----------------------------储存打卡信息---------------------------------------
query = on_command('查询')

@query.handle()
async def query(bot: Bot, event: MessageEvent,matcher: Matcher):
    user = event.get_user_id()
    msg = str(event.get_message())
    num_list = re.findall(r"\d+",msg)
    num_list = ["0"+num for num in num_list if len(num)<2]
    date = f"2024-{num_list[0]}-{num_list[1]}"
    if date in CONFIG2[user]:
        reply = f"{date}的计划为\n{CONFIG2[user][date]}"
    else:
        reply = "未查询到当天计划！"
    await matcher.finish(reply)
#编写连续打卡七天奖励提醒 完成
#初始化json一个数据结构，存储个人的各种信息（暂定只存储连续打卡信息，及未完成信息）
#每晚10.30之后才重置"unfinished_number"，（可以再加一个finished number），并判断是否应发送奖励提醒  完成
#连续未完成将得到警告  完成
#请假信息额外录入  

