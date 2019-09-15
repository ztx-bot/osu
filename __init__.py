# -*- coding: utf-8 -*-
# plugins/ppy/__init__.py

__plugin_name__ = 'osu'
__plugin_usage__ = '''osu 相关指令

开启推图功能 !map_notice on
关闭推图功能 !map_notice off
'''

from nonebot import on_command, CommandSession, logger, argparse
import nonebot
import os
from os import path
import requests
import json
from datetime import datetime, timedelta
import pytz

import util

TZ_SH = pytz.timezone('Asia/Shanghai')


DATA_DIR = path.join(util.plugin_dir(__file__), 'data')
FILE_SWITCH = path.join(DATA_DIR, 'switch.json')
FILE_RECORD = path.join(DATA_DIR, 'record.txt')


class DataManager(util.Singleton):
    __switch_list = None
    __record_time = None

    def __init__(self):
        # 创建目录
        if not path.isdir(DATA_DIR):
            os.mkdir(DATA_DIR)
        # 创建switch.json
        if not path.isfile(FILE_SWITCH):
            with open(FILE_SWITCH, 'w') as f:
                f.write('{}')  # 空字典
        try:
            with open(FILE_SWITCH, 'r') as f:
                obj = json.loads(f.read())
        except Exception as e:
            logger.error('file is not a json, rewriting')
            with open(FILE_SWITCH, 'w') as f:
                f.write('{}')

        with open(FILE_SWITCH, 'r') as f:
            self.__switch_list = json.loads(f.read())

        # 创建record.txt
        if not path.isfile(FILE_RECORD):
            with open(FILE_RECORD, 'w') as f:
                f.write('2019-01-01')  # 初始值
        try:
            with open(FILE_RECORD, 'r') as f:
                datetime.fromisoformat(f.read())
        except Exception as e:
            logger.error('record is not a time, rewriting')
            with open(FILE_RECORD, 'w') as f:
                f.write('2019-01-01')

        with open(FILE_RECORD, 'r') as f:
            self.__record_time = datetime.fromisoformat(
                f.read()).astimezone(TZ_SH)

    async def __save_switch(self):
        with open(FILE_SWITCH, 'w') as f:
            f.write(json.dumps(self.__switch_list))

    async def __save_record(self):
        with open(FILE_RECORD, 'w') as f:
            f.write(self.__record_time.isoformat())

    async def switch_on(self, group_id):
        if group_id in self.__switch_list:
            return
        self.__switch_list[group_id] = True
        await self.__save_switch()

    async def switch_off(self, group_id):
        if group_id not in self.__switch_list:
            return
        del self.__switch_list[group_id]
        await self.__save_switch()

    async def update_record(self, new_time):
        self.__record_time = new_time
        await self.__save_record()

    def get_groups(self):
        ret = []
        for group_id in self.__switch_list.keys():
            ret.append(group_id)
        return ret

    def get_last_time(self):
        return self.__record_time


data_manager = DataManager()


@on_command('map_notice', only_to_me=False, shell_like=True)
async def map_notice(session: CommandSession):
    USAGE = '''开启或关闭新图推送

使用方法：
!map_notice COMMAND=['on', 'off']
'''
    # 确保是群消息
    post_type = session.ctx.get('post_type', '')
    message_type = session.ctx.get('message_type', '')
    if post_type != 'message' or message_type != 'group':
        await session.send('该功能需要在群中使用')
        return
    # 确保群号存在
    group_id = session.ctx.get('group_id', 0)
    if group_id == 0:
        await session.send('获取群号失败')
        return
    # 确保是管理员进行设置
    role = session.ctx.get('sender', {}).get('role', 'member')
    if role != 'owner' and role != 'admin':
        await session.send('只能由群主或管理员进行设置，你的角色'+role)
        return
    parser = argparse.ArgumentParser(session=session, usage=USAGE)
    parser.add_argument('COMMAND', type=str)
    args = parser.parse_args(session.argv)
    if args.COMMAND == 'on':
        await data_manager.switch_on(group_id)
        await session.send('已开启新图推送功能')
        return
    if args.COMMAND == 'off':
        await data_manager.switch_off(group_id)
        await session.send('已关闭新图推送功能')
        return

    await session.send('参数错误，只允许on或off')


def GET_beatmapsets():
    url_home_page = 'https://osu.ppy.sh/beatmapsets/'
    rsp_home_page = requests.get(url_home_page)
    txt_home_page = rsp_home_page.text
    pos_begin = txt_home_page.find('{"beatmapsets":[{"id"')
    pos_end = txt_home_page.find('</script>', pos_begin)
    return json.loads(txt_home_page[pos_begin:pos_end])['beatmapsets']


def get_bms_info(beatmapset):
    # beatmapset_info 提取与处理一些关键的信息，用于之后的展示
    beatmaps = beatmapset['beatmaps']
    bm_infoset = []
    for beatmap in beatmaps:
        bm_info = {
            'mode': beatmap['mode'],
            'star': beatmap['difficulty_rating'],
            'diffname': beatmap['version']
            # 'url': beatmap['url']
        }
        bm_infoset.append(bm_info)
    bms_info = {
        'title': beatmapset['title'],
        'artist': beatmapset['artist'],
        'creator': beatmapset['creator'],
        # .strftime('%m/%d %H:%M:%S')
        'ranked_time': datetime.fromisoformat(beatmapset['ranked_date']).astimezone(TZ_SH),
        'url': 'https://osu.ppy.sh/beatmapsets/'+str(beatmapset['id']),
        'beatmaps': bm_infoset
    }
    return bms_info


async def get_bms_infoset(begin_time):
    # 尝试获取最新的几张图，他们需要晚于begin_time
    bms_infoset = []
    max_time = begin_time
    beatmapsets = GET_beatmapsets()
    for beatmapset in beatmapsets:
        bms_info = get_bms_info(beatmapset)
        if bms_info['ranked_time'] > begin_time:
            bms_infoset.append(bms_info)
            if bms_info['ranked_time'] > max_time:
                max_time = bms_info['ranked_time']
    return bms_infoset, max_time


def format_bms_info(bms):
    ret = ''
    ret += f"[{bms['ranked_time'].strftime('%m/%d %H:%M:%S')}]\n"
    ret += f"{bms['artist']} - {bms['title']} ({bms['creator']})\n"
    for bm in bms['beatmaps']:
        ret += f"{bm['diffname']} : {bm['mode']} {bm['star']: 2.2}☆\n"
    ret += bms['url']+'\n'
    return ret

# 最终目标，展示最近30分钟内的图，并且要晚于上次记录的时间，且少于50张图
@nonebot.scheduler.scheduled_job('interval', minutes=10)
async def _():
    groups = data_manager.get_groups()
    if len(groups) == 0:
        return
    bot = nonebot.get_bot()
    last_time = data_manager.get_last_time()
    recent_time = datetime.now(TZ_SH)-timedelta(minutes=30)
    begin_time = max(last_time, recent_time)
    bms_infoset, now_time = await get_bms_infoset(begin_time)
    if begin_time == now_time:
        return
    await data_manager.update_record(now_time)
    message = 'Recent ranked map:'
    for bms_info in bms_infoset:
        message += '\n'+format_bms_info(bms_info)
        logger.info(f"new ranked map [{bms_info['title']}]")
    for group_id in groups:
        await bot.send_group_msg(group_id=group_id, message=message)


# @on_command('testrank', only_to_me=False)
# async def testrank(session: CommandSession):
#     # 尝试获取最新的几张图
#     url_home_page = 'https://osu.ppy.sh/beatmapsets/'
#     rsp_home_page = requests.get(url_home_page)
#     txt_home_page = rsp_home_page.text
#     pos_begin = txt_home_page.find('{"beatmapsets":[{"id"')
#     pos_end = txt_home_page.find('</script>', pos_begin)
#     js_page0 = json.loads(txt_home_page[pos_begin:pos_end])
#     ctx = js_page0['cursor']  # approved_date and _id for next request
#     bms_page0 = js_page0['beatmapsets']
#     count = 0
#     reply = 'new ranked maps:\n'
#     for bms in bms_page0:
#         count += 1
#         if count == 10:
#             break
#         # get_bms_info(bms)
#         # 添加对时间的判断逻辑
#         reply += '\n'+format_bms_info(get_bms_info(bms))
#     await session.send(reply)
