"""Каталог официальных открытых протоколов соревнований и списков сборных команд ФСП России.

Источник: официальный сайт Общероссийской физкультурно-спортивной общественной организации
«Федерация спортивного программирования» (ОФСОО «ФСП») — https://fsp-russia.ru/about/documents/
Все документы опубликованы официально во исполнение Федерального закона от 04.12.2007 № 329-ФЗ
«О физической культуре и спорте в Российской Федерации».
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ProtocolSource:
    doc_id: str
    filename: str
    title: str
    discipline: str
    ekp_no: str
    event_date: str
    pdf_url: str
    is_text_pdf: bool = False
    default_rank: str | None = None


SOURCES: tuple[ProtocolSource, ...] = (
    ProtocolSource(
        doc_id="sbornaya_rf_2026",
        filename="sbornaya_2026.pdf",
        title="Список кандидатов в спортивные сборные команды РФ по спортивному программированию на 2026 год",
        discipline="все дисциплины",
        ekp_no="СБОРНАЯ-РФ-2026",
        event_date="2026-05-14",
        pdf_url="https://fsp-russia.ru/upload/iblock/503/e5miei2aikivxs93d6qz2iqfnfaf0xp1.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_algo_otbor",
        filename="algo_otbor.pdf",
        title="Итоговый протокол отборочного этапа Кубка России по спортивному программированию (программирование алгоритмическое)",
        discipline="программирование алгоритмическое",
        ekp_no="2101770020035561",
        event_date="2025-04-26",
        pdf_url="https://fsp-russia.ru/upload/iblock/969/h77wns4jpn7z3pmkrm0azxfye6era08y.pdf",
        is_text_pdf=True,
    ),
    ProtocolSource(
        doc_id="kr_2025_prod_otbor",
        filename="hack_otbor.pdf",
        title="Итоговый протокол отборочного этапа Кубка России по спортивному программированию (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="2101000020035559",
        event_date="2025-04-28",
        pdf_url="https://fsp-russia.ru/upload/iblock/6cb/txbuswvkginckkbtbwtkata1wbfukqda.pdf",
        is_text_pdf=True,
    ),
    ProtocolSource(
        doc_id="kr_2025_ib_otbor",
        filename="ib_otbor.pdf",
        title="Итоговый протокол отборочного этапа Кубка России по спортивному программированию (программирование систем ИБ)",
        discipline="программирование систем информационной безопасности",
        ekp_no="2101000020041809",
        event_date="2025-04-26",
        pdf_url="https://fsp-russia.ru/upload/iblock/922/9uxtofnr07t1n3lha1o0ku1anbqndqe1.pdf",
        is_text_pdf=True,
    ),
    ProtocolSource(
        doc_id="chr_2025_prod_final",
        filename="chr_2025_prod.pdf",
        title="Итоговые протоколы Чемпионата России по спортивному программированию (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="2101590019043742",
        event_date="2025-11-23",
        pdf_url="https://fsp-russia.ru/upload/iblock/138/tb1vnqokiid4fiwdb40evznavplvmysg.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_prod_final",
        filename="kr_2025_hack.pdf",
        title="Итоговый протокол финала Кубка России по спортивному программированию (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="2101620020035562",
        event_date="2025-05-22",
        pdf_url="https://fsp-russia.ru/upload/iblock/f5e/8ma6l935b05m4q88wi5n24ne23p7qbya.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_algo_final",
        filename="kr_2025_algo.pdf",
        title="Итоговый протокол финала Кубка России по спортивному программированию (программирование алгоритмическое)",
        discipline="программирование алгоритмическое",
        ekp_no="2101620020035561",
        event_date="2025-05-22",
        pdf_url="https://fsp-russia.ru/upload/iblock/2fd/go7v4ekr13s1wwepx7poocbxgxd2u92i.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_ib_final",
        filename="ib_final.pdf",
        title="Итоговый протокол финала Кубка России по спортивному программированию (программирование систем ИБ)",
        discipline="программирование систем информационной безопасности",
        ekp_no="2101620020041809",
        event_date="2025-05-22",
        pdf_url="https://fsp-russia.ru/upload/iblock/27f/5hs99w6a2n362vlqnonn51110vlhkvc5.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_robo_otbor",
        filename="kr_2025_robo.pdf",
        title="Итоговый протокол отборочного этапа Кубка России по спортивному программированию (программирование робототехники)",
        discipline="программирование робототехники",
        ekp_no="2101000020035560",
        event_date="2025-04-27",
        pdf_url="https://fsp-russia.ru/upload/iblock/b0d/f4ikw0r1e2qwmvt3usudy5ve81r3ykrf.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_robo_otbor",
        filename="kr_2026_robo.pdf",
        title="Протокол отборочного этапа Кубка России 2026 (программирование робототехники)",
        discipline="программирование робототехники",
        ekp_no="КР-2026-РОБО",
        event_date="2026-04-20",
        pdf_url="https://fsp-russia.ru/upload/iblock/092/us9qvdfvm0kwathyo67wjuvje8c9v1ra.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_prod_otbor",
        filename="kr_2026_prod_spravka.pdf",
        title="Протокол отборочного этапа Кубка России 2026 (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="КР-2026-ПРОД",
        event_date="2026-04-20",
        pdf_url="https://fsp-russia.ru/upload/iblock/120/f8mtqy9398owua73i24f999rly5fovnf.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_bas_otbor",
        filename="kr_2026_bas.pdf",
        title="Протокол отборочного этапа Кубка России 2026 (программирование БАС)",
        discipline="программирование беспилотных авиационных систем",
        ekp_no="КР-2026-БАС",
        event_date="2026-04-20",
        pdf_url="https://fsp-russia.ru/upload/iblock/5c8/p3ikqnt1g9iw1kvczvxgv5qjhv2x9tya.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_sib_otbor",
        filename="kr_2026_sib.pdf",
        title="Протокол отборочного этапа Кубка России 2026 (программирование систем ИБ)",
        discipline="программирование систем информационной безопасности",
        ekp_no="КР-2026-СИБ",
        event_date="2026-04-20",
        pdf_url="https://fsp-russia.ru/upload/iblock/9db/e6rp6ekcljtfofzw99bao13a8mpav8i9.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_algo_otbor",
        filename="kr_2026_algo.pdf",
        title="Протокол отборочного этапа Кубка России 2026 (программирование алгоритмическое)",
        discipline="программирование алгоритмическое",
        ekp_no="КР-2026-АЛГО",
        event_date="2026-04-20",
        pdf_url="https://fsp-russia.ru/upload/iblock/fff/rof2o18vujo5me8hfep08nn3bp6sd3lv.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2026_algo_table",
        filename="tur_2026_algo.pdf",
        title="Турнирная таблица Кубка России 2026 (программирование алгоритмическое)",
        discipline="программирование алгоритмическое",
        ekp_no="КР-2026-АЛГО-ТАБЛ",
        event_date="2026-05-15",
        pdf_url="https://fsp-russia.ru/upload/iblock/a0b/f0gja1njckgfwu6heobl1o3z4021wlpg.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kf_2026_final",
        filename="kf_2026.pdf",
        title="Итоговые протоколы Кубка Федерации спортивного программирования 2026",
        discipline="программирование продуктовое",
        ekp_no="КФ-2026",
        event_date="2026-10-17",
        pdf_url="https://fsp-russia.ru/upload/iblock/ef1/15a3exjee1npp1vux0sl5qborm4n6q3r.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="pfo_2026_prod",
        filename="pfo_2026_prod.pdf",
        title="Итоговые протоколы Чемпионата и Первенства ПФО 2026 (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="ПФО-2026-ПРОД",
        event_date="2026-10-06",
        pdf_url="https://fsp-russia.ru/upload/iblock/f68/xqhh07qp40z3mfi8lraxt53842qlw772.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="cfo_2026_prod",
        filename="cfo_2026_prod.pdf",
        title="Итоговые протоколы Чемпионата и Первенства ЦФО 2026 (программирование продуктовое)",
        discipline="программирование продуктовое",
        ekp_no="ЦФО-2026-ПРОД",
        event_date="2026-10-06",
        pdf_url="https://fsp-russia.ru/upload/iblock/a3d/u4g6723ljtd8cxp3fa1kfhbs01f7cfbs.pdf",
        is_text_pdf=False,
    ),
    ProtocolSource(
        doc_id="kr_2025_sk_otbor",
        filename="sk_otbor.pdf",
        title="Справка о составе и квалификации судейской коллегии отборочного этапа Кубка России",
        discipline="все дисциплины",
        ekp_no="2101000020035559",
        event_date="2025-04-28",
        pdf_url="https://fsp-russia.ru/upload/iblock/058/g6txm9cku30ktl7o93u8xw40kpjv9kin.pdf",
        is_text_pdf=False,
    ),
)

SOURCE_BY_ID = {s.doc_id: s for s in SOURCES}
SOURCE_BY_FILENAME = {s.filename: s for s in SOURCES}
