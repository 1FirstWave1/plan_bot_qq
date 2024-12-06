import logging, codecs
from datetime import datetime
import requests
import time
import json
from nonebot.permission import SUPERUSER
from nonebot import on_command, on_startswith, on_keyword, on_fullmatch, on_message, on_notice
from nonebot.matcher import Matcher
from nonebot.params import ArgPlainText, CommandArg, ArgStr
from nonebot.adapters.onebot.v11 import Message, MessageSegment, escape
from nonebot.adapters.onebot.v11 import Bot, GroupMessageEvent, MessageEvent, PrivateMessageEvent
from nonebot.adapters.onebot.v11 import GROUP_ADMIN, GROUP_OWNER, GROUP_MEMBER
from nonebot.typing import T_State
from nonebot.adapters.onebot.v11 import Bot, Event, Message
from nonebot.rule import to_me
from nonebot.log import logger
from nonebot.params import CommandArg, ArgStr
#尝试直接使用openai而不是langchain
from openai import OpenAI
from dotenv import load_dotenv

_ = load_dotenv(dotenv_path='src/plugins/env.env')
model_name = 'gpt-4o-mini'
Amadeus = OpenAI()

def response_from_llm(message_list):
    global Amadeus
    completion = Amadeus.chat.completions.create(model=model_name, messages=message_list,temperature=0)
    print(completion.choices[0].message.content)
    return completion.choices[0].message.content



rc = lambda role, content: {"role": role, "content": content}
remove_colon = lambda string: string[string.index(":") + 1:] if (":" in string and string.index(":") <= 10) else string
messageList = [
    rc("system",
       "You are Amadeus, a chat robot trained by 猖狂的橙子.You can execute many instructions start with '/', such as '/e','/匹配'."),
]

def makedata(thisinput: str = "", thisuser: str = "user", lastuser: str = "user", lastinput: str = "",
             lastreply: str = ""):
    global messageList, messageList1
    if lastreply != "" and lastinput != "":
        # messageList.append(rc(lastuser, lastinput))
        #保存上一轮的回答
        messageList.append(rc("assistant", lastreply))
    messageList.append(rc(thisuser, thisinput))

    leng = len(messageList)
    print(f'len:{leng}')
    try:
        #过长从头开始，保留系统提示词，所以多搞了个messageList1
        if leng > 98:
            messageList = [rc("system",
        "You are Amadeus, a chat robot trained by 猖狂的橙子.You can execute many instructions start with '/', such as '/e','/匹配'."),]
    except ValueError:
        messageList = [rc(thisuser, thisinput)]
    return messageList



frienddesc = {}

async def getfriendlist(bot: Bot):
    friendlist = await bot.get_friend_list()
    global frienddesc
    for i in friendlist:
        frienddesc[i['user_id']] = f"{i['user_remark']}/{i['user_name']}"


async def resolveqq(bot: Bot, qq: int, gpid: int = 0):
    if gpid == 0:
        try:
            return frienddesc[str(qq)]
        except:
            await getfriendlist(bot=bot)
            try:
                return frienddesc[str(qq)]
            except Exception as e:
                print(f'获取好友备注失败：{qq}-{e}')
                return str(qq)
    else:
        try:
            data = await bot.get_group_member_info(group_id=gpid, user_id=qq)
            return f"{data['user_name']}/{data['user_displayname']}"
        except Exception as e:
            print(f'获取群名片失败：{qq}-{e}')
            return str(qq)


lastinput = ""
lastreply = ""
lastuser = 0

pp = on_message(rule=to_me(), priority=98)


@pp.handle()
async def handle_city(bot: Bot, event: MessageEvent):
    global url, lastuser, lastinput, lastreply, headers
    user = event.user_id
    city = str(event.get_message())
    if 'CQ:image' in city or 'CQ:face' in city:
        return
    # try:
    #     userinfo = await resolveqq(bot=bot, qq=user, gpid=json.loads(event.json())["group_id"])
    # except:
    #     userinfo = await resolveqq(bot=bot, qq=user, gpid=0)
    # city = f'{userinfo}:' + city
    try:
        city = f'{str(event.reply.sender.user_id)}:"{event.reply.message}"' + city
    except Exception as e:
        pass
    msg =response_from_llm(makedata(thisinput=city, lastinput=lastinput, lastreply=lastreply))

    open('record.txt', 'a', encoding='utf8').write(
        f'{time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())}-{user}:{city} AI:{msg}\n')
    lastinput = city
    lastreply = msg
    if user == lastuser:
        await pp.finish(message=msg)
    else:
        lastuser = user
        await pp.finish(message=msg, at_sender=True)


abstract = on_command("role", priority=5, block=True)


@abstract.handle()
async def _(state: T_State, arg: Message = CommandArg()):
    if arg.extract_plain_text().strip():
        state["r"] = arg.extract_plain_text().strip()


@abstract.got("r", prompt="你想以什么身份给神经网络输入数据？(user/system/assistant)")
async def _(bot: Bot, event: Event, r: str = ArgStr("r")):
    global headers
    await abstract.send(f"你将以{r}的身份说话。你想说什么？", at_sender=True)


@abstract.got("c")
async def _(bot: Bot, event: Event, r: str = ArgStr("r"), c: str = ArgStr("c")):
    global headers
    msg = ""
    try:
        r = requests.post(url, headers=headers, data=makedata(thisuser=r, thisinput=c), stream=True)
        try:
            ls = []
            for line in r.iter_lines():
                if line:
                    text = line.decode("utf-8")  # 将字节流解码为文本
                    print(text)  # 打印每行文本数据
                    ls.append(text)
                msg = '\n'.join(ls)
                print(msg)
        except:
            msg = r.text
    except Exception as e:
        msg = str(e)
    await abstract.send(msg)


abstract = on_command("showhistory", priority=5, block=True)


@abstract.handle()
async def _(state: T_State, arg: Message = CommandArg()):
    global messageList
    await abstract.finish(str([{v['role']: v['content']} for v in messageList[1:]])[:2000])


abstract = on_command("clear", priority=5, block=True)


@abstract.handle()
async def _(state: T_State, arg: Message = CommandArg()):
    global messageList
    messageList = [
        rc("system",
           "You are Amadeus, a chat robot trained by 猖狂的橙子.You can execute many instructions start with '/', such as '/e','/匹配'."),
    ]
    await abstract.finish("记忆清除成功")


abstract = on_command("changeidentity", priority=5, block=True)


@abstract.handle()
async def _(state: T_State, arg: Message = CommandArg()):
    if arg.extract_plain_text().strip():
        state["i"] = arg.extract_plain_text().strip()


@abstract.got("i", prompt="请输入新身份的名字：")
async def _(bot: Bot, event: Event, i: str = ArgStr("i")):
    global messageList
    #重置消息队列
    messageList = [
        rc("system",
           f"You are {i}. You can execute many instructions start with '/'."),
    ]


@abstract.got("c", prompt="请输入新身份的描述：")
async def _(bot: Bot, event: Event, i: str = ArgStr("i"), c: str = ArgStr("c")):
    global headers, messageList
    messageList = [
        rc("system",
           f"请你更改扮演的角色，你现在不是GPT，而是一个{c}，名叫{i}。你知晓{i}的设定直接开始以角色身份进行输出，具体人设自行补充，不得输出任何无关内容.我是用户，我的第一句话是："),
    ]
    await abstract.send(f"新身份{i}已经准备好，请at我开始聊天。")

#获取用户群昵称
abstract = on_command("resolveme", priority=5, block=True)


@abstract.handle()
async def _(bot: Bot, event: GroupMessageEvent, state: T_State, arg: Message = CommandArg()):
    s = await resolveqq(bot=bot, qq=event.user_id, gpid=event.group_id)
    await abstract.finish(s)


abstract = on_command("resolveme", priority=5, block=True)


@abstract.handle()
async def _(bot: Bot, event: PrivateMessageEvent, state: T_State, arg: Message = CommandArg()):
    s = await resolveqq(bot=bot, qq=event.user_id, gpid=0)
    await abstract.finish(s)


# 获取robot好友列表
abstract = on_command("fln", priority=5, block=True)


@abstract.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State, arg: Message = CommandArg()):
    try:
        friendlist = await bot.get_friend_list()
        await abstract.finish(str(friendlist))
    except Exception as e:
        print(f"出错：{e}")


#获取群id
abstract = on_command("gpid", priority=5, block=True)


@abstract.handle()
async def _(bot: Bot, event: MessageEvent, state: T_State, arg: Message = CommandArg()):
    await abstract.finish(str(json.loads(event.json())["group_id"]))



