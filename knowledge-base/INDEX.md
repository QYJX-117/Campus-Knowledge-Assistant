---
id: INDEX
title: 河海大学校园服务知识库 — 总索引
category: 索引
tags: [索引, 目录, 导航, 知识库]
source: internal
updated: 2026-07-18
---

# 河海大学校园服务知识库 v3.0

> 覆盖河海大学三校区（西康路、江宁、常州金坛）的完整校园服务信息
> 用于 RAG 文档入库、分块检索、AI 助手问答
> 最近全量更新: 2026-07-18

---

## 知识库结构

### 零、学校概况

| ID | 文档 | 完成度 | 说明 |
|----|------|:------:|------|
| [00-hhu](00_hhu/00-hhu.md) | 河海大学概况 | 🟢 100% | 学校简介、历史沿革、校领导、校区、学科排名，面向校外访客 |

### 一、学习资源

| ID | 文档 | 完成度 | 说明 |
|----|------|:------:|------|
| [01-lib](01_lib/01-lib.md) | 图书馆 | 🟢 100% | 图书馆、数据库、自习空间等学术资源服务 |

### 二、生活服务

| ID | 文档 | 完成度 | 说明 |
|----|------|:------:|------|
| [02-canteen](02_canteen/02-canteen.md) | 食堂餐饮 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [03-dorm](03_dorm/03-dorm.md) | 宿舍生活 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [06-health](06_health/06-health.md) | 医疗健康 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [07-sports](07_sports/07-sports.md) | 体育设施 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [08-transport](08_transport/08-transport.md) | 交通出行 | N/A | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [09-post](09_post/09-post.md) | 快递邮政 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [13-security](13_security/13-security.md) | 安全保卫 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [15-mental](15_mental/15-mental.md) | 心理健康 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |
| [18-service](18_service/18-service.md) | 校园服务 | 🟢 100% | 餐饮、住宿、医疗、交通、安全等日常生活保障 |

### 三、基础设施建设

| ID | 文档 | 完成度 | 说明 |
|----|------|:------:|------|
| [04-card](04_card/04-card.md) | 校园卡 | 🟢 100% | 校园卡、网络、IT等信息化基础设施 |
| [05-it](05_it/05-it.md) | 网络与IT服务 | 🟢 100% | 校园卡、网络、IT等信息化基础设施 |

### 四、教学科研

| ID | 文档 | 完成度 | 说明 |
|----|------|:------:|------|
| [10-academic](10_academic/10-academic.md) | 教务教学 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |
| [11-aid](11_aid/11-aid.md) | 学工奖助 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |
| [12-finance](12_finance/12-finance.md) | 财务缴费 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |
| [14-career](14_career/14-career.md) | 就业发展 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |
| [16-intl](16_intl/16-intl.md) | 国际交流 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |
| [17-admission](17_admission/17-admission.md) | 招生信息 | 🟢 100% | 教务、奖助、财务、就业、国际交流等教学科研管理 |

---

## 跨模块关联矩阵

下表标注了各知识模块之间的关联强度（● 强关联 / ○ 一般关联）：

|  | lib | canteen | dorm | card | it | health | sports | transport | post | academic | aid | finance | security | career | mental | intl | admission | service |
|------|-----|---------|------|------|----|--------|--------|-----------|------|----------|-----|---------|----------|--------|--------|------|-----------|---------|
| **01-lib** | — | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| **02-canteen** | ○ | — | ● | ○ | ○ | ● | ● | ● | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **03-dorm** | ○ | ● | — | ○ | ○ | ● | ● | ● | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **04-card** | ○ | ○ | ○ | — | ● | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| **05-it** | ○ | ○ | ○ | ● | — | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ |
| **06-health** | ○ | ● | ● | ○ | ○ | — | ● | ● | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **07-sports** | ○ | ● | ● | ○ | ○ | ● | — | ● | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **08-transport** | ○ | ● | ● | ○ | ○ | ● | ● | — | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **09-post** | ○ | ● | ● | ○ | ○ | ● | ● | ● | — | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | ● |
| **10-academic** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | — | ● | ● | ○ | ● | ○ | ● | ● | ○ |
| **11-aid** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | — | ● | ○ | ● | ○ | ● | ● | ○ |
| **12-finance** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ● | — | ○ | ● | ○ | ● | ● | ○ |
| **13-security** | ○ | ● | ● | ○ | ○ | ● | ● | ● | ● | ○ | ○ | ○ | — | ○ | ● | ○ | ○ | ● |
| **14-career** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ● | ● | ○ | — | ○ | ● | ● | ○ |
| **15-mental** | ○ | ● | ● | ○ | ○ | ● | ● | ● | ● | ○ | ○ | ○ | ● | ○ | — | ○ | ○ | ● |
| **16-intl** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ● | ● | ○ | ● | ○ | — | ● | ○ |
| **17-admission** | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ○ | ● | ● | ● | ○ | ● | ○ | ● | — | ○ |
| **18-service** | ○ | ● | ● | ○ | ○ | ● | ● | ● | ● | ○ | ○ | ○ | ● | ○ | ● | ○ | ○ | — |

---

## 关键词快速检索

- **VPN**: [05-it](05_it/05-it.md)
- **WiFi**: [05-it](05_it/05-it.md)
- **一卡通**: [04-card](04_card/04-card.md)
- **一网通办**: [05-it](05_it/05-it.md)
- **三方协议**: [14-career](14_career/14-career.md)
- **交换生**: [16-intl](16_intl/16-intl.md)
- **住宿**: [03-dorm](03_dorm/03-dorm.md)
- **住宿费**: [12-finance](12_finance/12-finance.md)
- **体检**: [06-health](06_health/06-health.md)
- **体测**: [07-sports](07_sports/07-sports.md)
- **体育馆**: [07-sports](07_sports/07-sports.md)
- **借阅**: [01-lib](01_lib/01-lib.md)
- **健身房**: [07-sports](07_sports/07-sports.md)
- **充值**: [04-card](04_card/04-card.md)
- **公交**: [08-transport](08_transport/08-transport.md)
- **共享单车**: [08-transport](08_transport/08-transport.md)
- **出国**: [16-intl](16_intl/16-intl.md)
- **分数线**: [17-admission](17_admission/17-admission.md)
- **助学贷款**: [11-aid](11_aid/11-aid.md)
- **助学金**: [11-aid](11_aid/11-aid.md)
- **勤工助学**: [11-aid](11_aid/11-aid.md)
- **包裹**: [09-post](09_post/09-post.md)
- **医保**: [06-health](06_health/06-health.md)
- **危机干预**: [15-mental](15_mental/15-mental.md)
- **后勤**: [18-service](18_service/18-service.md)
- **困难补助**: [11-aid](11_aid/11-aid.md)
- **国际处**: [16-intl](16_intl/16-intl.md)
- **图书馆**: [01-lib](01_lib/01-lib.md)
- **地铁**: [08-transport](08_transport/08-transport.md)
- **外卖**: [02-canteen](02_canteen/02-canteen.md)
- **夜宵**: [02-canteen](02_canteen/02-canteen.md)
- **失物招领**: [18-service](18_service/18-service.md)
- **奖学金**: [11-aid](11_aid/11-aid.md)
- **学籍**: [10-academic](10_academic/10-academic.md)
- **学费**: [12-finance](12_finance/12-finance.md)
- **安保**: [13-security](13_security/13-security.md)
- **实习**: [14-career](14_career/14-career.md)
- **宣讲会**: [14-career](14_career/14-career.md)
- **宿舍**: [03-dorm](03_dorm/03-dorm.md)
- **就业**: [14-career](14_career/14-career.md)
- **就诊**: [06-health](06_health/06-health.md)
- **录取**: [17-admission](17_admission/17-admission.md)
- **心理中心**: [15-mental](15_mental/15-mental.md)
- **心理咨询**: [15-mental](15_mental/15-mental.md)
- **心理普查**: [15-mental](15_mental/15-mental.md)
- **快递**: [09-post](09_post/09-post.md)
- **成绩**: [10-academic](10_academic/10-academic.md)
- **户籍**: [13-security](13_security/13-security.md)
- **打印**: [18-service](18_service/18-service.md)
- **报案**: [13-security](13_security/13-security.md)
- **报销**: [06-health](06_health/06-health.md), [12-finance](12_finance/12-finance.md)
- **招聘**: [14-career](14_career/14-career.md)
- **挂失**: [04-card](04_card/04-card.md)
- **操场**: [07-sports](07_sports/07-sports.md)
- **收发室**: [09-post](09_post/09-post.md)
- **教务系统**: [10-academic](10_academic/10-academic.md)
- **数据库**: [01-lib](01_lib/01-lib.md)
- **本科招生**: [17-admission](17_admission/17-admission.md)
- **校区间交通**: [08-transport](08_transport/08-transport.md)
- **校医院**: [06-health](06_health/06-health.md)
- **校历**: [10-academic](10_academic/10-academic.md)
- **校园卡**: [04-card](04_card/04-card.md)
- **校园网**: [05-it](05_it/05-it.md)
- **校车**: [08-transport](08_transport/08-transport.md)
- **档案**: [14-career](14_career/14-career.md)
- **正版软件**: [05-it](05_it/05-it.md)
- **民族餐厅**: [02-canteen](02_canteen/02-canteen.md)
- **水电**: [03-dorm](03_dorm/03-dorm.md)
- **洗衣**: [03-dorm](03_dorm/03-dorm.md)
- **消防**: [13-security](13_security/13-security.md)
- **游泳馆**: [07-sports](07_sports/07-sports.md)
- **班车**: [08-transport](08_transport/08-transport.md)
- **理发**: [18-service](18_service/18-service.md)
- **留学**: [16-intl](16_intl/16-intl.md)
- **留学生招生**: [17-admission](17_admission/17-admission.md)
- **监控**: [13-security](13_security/13-security.md)
- **研究生招生**: [17-admission](17_admission/17-admission.md)
- **科技查新**: [01-lib](01_lib/01-lib.md)
- **空调**: [03-dorm](03_dorm/03-dorm.md)
- **维修**: [18-service](18_service/18-service.md)
- **缴费平台**: [12-finance](12_finance/12-finance.md)
- **考试**: [10-academic](10_academic/10-academic.md)
- **自习**: [01-lib](01_lib/01-lib.md)
- **菜鸟驿站**: [09-post](09_post/09-post.md)
- **访学**: [16-intl](16_intl/16-intl.md)
- **语言**: [16-intl](16_intl/16-intl.md)
- **超市**: [18-service](18_service/18-service.md)
- **转诊**: [06-health](06_health/06-health.md)
- **选课**: [10-academic](10_academic/10-academic.md)
- **邮政**: [09-post](09_post/09-post.md)
- **邮箱**: [05-it](05_it/05-it.md)
- **银行卡**: [12-finance](12_finance/12-finance.md)
- **门禁**: [03-dorm](03_dorm/03-dorm.md), [04-card](04_card/04-card.md), [13-security](13_security/13-security.md)
- **阅览室**: [01-lib](01_lib/01-lib.md)
- **食堂**: [02-canteen](02_canteen/02-canteen.md)
- **餐饮**: [02-canteen](02_canteen/02-canteen.md)

---

## 数据源清单

| 模块 | 主要数据源 | 爬虫状态 |
|------|-----------|:--------:|
| 图书馆 | https://lib.hhu.edu.cn | ✅ 已爬取 |
| 食堂餐饮 | https://hq.hhu.edu.cn | ⏳ 待爬取 |
| 宿舍生活 | https://hq.hhu.edu.cn | ⏳ 待爬取 |
| 校园卡 | https://ecard.hhu.edu.cn | ⏳ 待爬取 |
| 网络与IT服务 | https://hhic.hhu.edu.cn | ⏳ 待爬取 |
| 医疗健康 | https://hospital.hhu.edu.cn | ⏳ 待爬取 |
| 体育设施 | https://tyb.hhu.edu.cn | ⏳ 待爬取 |
| 交通出行 | https://hq.hhu.edu.cn | ⏳ 待爬取 |
| 快递邮政 | https://hq.hhu.edu.cn | ⏳ 待爬取 |
| 教务教学 | https://jwc.hhu.edu.cn | ⏳ 待爬取 |
| 学工奖助 | https://xsc.hhu.edu.cn | ⏳ 待爬取 |
| 财务缴费 | https://cwc.hhu.edu.cn | ⏳ 待爬取 |
| 安全保卫 | https://bwc.hhu.edu.cn | ⏳ 待爬取 |
| 就业发展 | https://job.hhu.edu.cn | ⏳ 待爬取 |
| 心理健康 | https://xsc.hhu.edu.cn | ⏳ 待爬取 |
| 国际交流 | https://ie.hhu.edu.cn | ⏳ 待爬取 |
| 招生信息 | https://zsw.hhu.edu.cn | ⏳ 待爬取 |
| 校园服务 | https://hq.hhu.edu.cn | ⏳ 待爬取 |

---

## 文档编写规范

每个知识模块文档遵循统一格式：

1. **YAML Frontmatter**: 包含 id, title, category, tags, source, updated, status
2. **章节编号**: `X.Y` 格式（X=模块号, Y=子章节号）
3. **Checkbox 机制**: `[x]` = 已核实填写, `[ ]` = 待核实
4. **数据来源标注**: 每个章节标注信息来源
5. **更新周期**: 明确标注核实频率

### 文档状态标识

- `draft`: 模板阶段，大部分字段待填写
- `partial`: 部分字段已填写，核心信息可用
- `complete`: 所有核心字段已核实填写
- `verified`: 二次核验通过

---

> 知识库版本: v3.0 | 生成时间: 2026-07-18 | 总模块数: 18
> 维护：请定期更新各模块 [x] 字段，保持信息时效性
