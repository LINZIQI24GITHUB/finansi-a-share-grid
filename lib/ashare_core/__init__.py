"""ashare_core —— A 股 skill 包的共享内核。

设计约束（商用）：
1. 本包的业务代码只能依赖这里定义的 schema，不能依赖具体数据源；
2. 数据源实现统一放在 providers/ 下，每个实现必须声明 capabilities；
3. 所有落盘数据都要带 source / fetched_at，便于换源后重建与追溯。
"""

__version__ = "0.2.0"
