"""本机没装 IPython（板上 Jupyter 自带）。

启动本 p11_start.ipynb 里只有一处用到它：`from IPython import get_ipython` +
`if get_ipython() is not None: run_line_magic('xmode','Plain')`。
无头跑这段代码时这里返回 None，等价于「不在 Jupyter 里」，正是要验证的那条路径。

⚠️ 只给 build/check_start_notebook.py 和 check_merged.py 的无头检查用；
   板上跑的是真 IPython，不会走到这里。
"""


def get_ipython():
    return None
