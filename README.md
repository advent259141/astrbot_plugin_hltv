# 基于HLTV的cs数据查询插件

这是一个利用playwright实现的基于HLTV.org网站数据的cs赛事数据查询插件
使用时可能需要代理或梯子，否则容易出现查询失败

# 使用前置
使用该插件需要在astrbot控制台安装一些额外的库

pip install beautifulsoup4
pip install playwright
pip install pillow
pip install python-utils
pip install cloudscraper
pip install tzlocal
pip install lxml

在这些库安装完成后打开cmd，输入

playwright install chromium

做完这些后如果启动插件没有报错，并且你的设备已魔法上网，那么就可以愉快地使用该插件了


# 指令
/hltv_help  即可查看所有可用指令
目前包括查询战队信息，选手信息，近期比赛，比赛结果详细以及top战队查询，若希望有更多功能可提issue

# 支持
若使用出现问题，欢迎提issue或在群里艾特Jason.Joestar
