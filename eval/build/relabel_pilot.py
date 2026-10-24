"""Phase 2 relabel of the pilot golden questions (q01-q60).

The pilot corpus had two AMLC documents. With GoTRACS (the current reporting rules)
and the sector regulators indexed, a question can be answered by more provisions:

- gold: general AMLC rules that answer it (2018 IRR, 2021 RRG, GoTRACS, AMLC guidelines)
- also: sector restatements that state the same fact (BSP MORB, SEC MC 16, IC circulars,
        the DNFBP guidelines); correct evidence, but not the general rule

Each added label was read against the retrieved text (see eval/review); this script
only applies them and is kept so the change is reviewable.
"""
GOLD_ADD = {
    "q01": ["gotracs2024:chi:sec2:sg"], "q02": ["gotracs2024:chi:sec2:sg"], "q03": ["gotracs2024:chi:sec2:sg"],
    "q04": ["gotracs2024:chi:sec2:sg", "gotracs2024:chii:part1:sec2:s2.17"],
    "q05": ["gotracs2024:chi:sec4:s4.2"], "q06": ["gotracs2024:chi:sec5:s5.4:sd"], "q07": ["gotracs2024:chi:sec5:s5.4:sd"],
    "q16": ["gotracs2024:chi:sec2:se", "sanctions2021:s4.1", "bo2018:sec2:sd"],
    "q18": ["admin_sanctions2017:rulev:sec1"],
    "q23": ["gotracs2024:chi:sec5:s5.4:sc:s3:sviii"],
    "q24": ["gotracs2024:chi:sec5:s5.3:sc:s3"],
    "q25": ["gotracs2024:chi:sec5:s5.4:sc:s3:si"], "q26": ["gotracs2024:chi:sec5:s5.4:sc:s3:siv"],
    "q28": ["gotracs2024:chii:part1:sec4:s4.8"], "q29": ["gotracs2024:chi:sec2:sw"], "q30": ["gotracs2024:chi:sec2:sv:s1"],
    "q32": ["gotracs2024:chi:sec5:s5.4:sb"],
    "q41": ["irr2018:rule18:sec6:s6.3"], "q43": ["irr2018:rule18:sec6:s6.5", "irr2018:rule24:sec1"],
    "q50": ["gotracs2024:chi:sec6:s6.1"],
}
# GoTRACS 5.4(d) words the occurrence date differently from IRR Rule 22, Sec. 2
MUST_CONTAIN = {"q07": ["establishment of suspicion|determination of the suspicious nature|decides with finality|end of the determination period"]}

ALSO = {
    "q01": ["dnfbp2021:titleii:sec3:sh", "sec_mc16_2018:ch7:sec7.3"], "q02": ["dnfbp2021:titleii:sec3:sh"],
    "q04": ["dnfbp2021:titleii:sec3:sh"],
    "q05": ["bsp_morb_p9:sec922", "ic_cl2019_65:sec21", "dnfbp2021:titlevi:sec43", "sec_mc16_2018:ch7:sec7.5"],
    "q06": ["dnfbp2021:titlevi:sec43"], "q07": ["sec_mc16_2018:ch7:sec7.5", "dnfbp2021:titlevi:sec43"],
    "q08": ["ic_cl2019_65:sec21", "bsp_morb_p9:sec922", "sec_mc16_2018:ch7:sec7.5"],
    "q09": ["ic_cl2018_48:titlevi:sec48", "dnfbp2021:titlev:sec40", "bsp_morb_p9:sec924", "sec_mc16_2018:ch6:sec6.2"],
    "q10": ["bsp_morb_p9:sec924:sclosedaccountsandterminatedrelationships"],
    "q11": ["bsp_morb_p9:sec924:sretentionofrecordswheretheaccountorcusto", "ic_cl2018_48:titlevi:sec48",
            "dnfbp2021:titlev:sec40", "sec_mc16_2018:ch6:sec6.3"],
    "q12": ["bsp_morb_p9:sec911:sriskassessment", "dnfbp2021:titleiii:sec5:sf", "ic_cl2019_65:sec2", "ic_cl2024_16:main"],
    "q14": ["ic_cl2019_65:sec4"], "q16": ["bsp_morb_p9:sec904"],
    "q17": ["sec_mc16_2018:ch5:sec5.j.1", "bsp_morb_p9:sec923:sforeignexchangedealersmoneychangersremit"],
    "q29": ["sec_mc16_2018:ch7:sec7.4"], "q30": ["sec_mc16_2018:ch7:sec7.4"],
    "q31": ["sec_mc16_2018:ch7:sec7.6", "bsp_morb_p9:sec922"], "q32": ["sec_mc16_2018:ch7:sec7.7"],
    "q33": ["dnfbp2021:titlevi:sec48"],
    "q34": ["sec_mc16_2018:ch7:sec7.10", "bsp_morb_p9:sec922:sconfidentialityprovision", "dnfbp2021:titlevi:sec46"],
    "q35": ["bsp_morb_p9:sec922:ssafeharborprovision", "sec_mc16_2018:ch7:sec7.11", "ic_cl2018_48:titlevii:sec59",
            "dnfbp2021:titlevi:sec47"],
    "q37": ["bsp_morb_p9:sec921"], "q38": ["ic_cl2019_65:sec19", "sec_mc16_2018:ch5:sec5.c.5"],
    "q39": ["sec_mc16_2018:ch5:sec5.c.3", "ic_cl2019_65:sec11"],
    "q40": ["bsp_morb_p9:sec921:scustomeracceptanceandidentificationpolic", "dnfbp2021:titleiv:sec27"],
    "q41": ["bsp_morb_p9:sec921:scustomeridentification", "ic_cl2019_65:sec16", "ic_cl2019_65:sec7:sb"],
    "q42": ["ic_cl2019_65:sec6:sd"],
    "q43": ["ic_cl2019_65:sec13", "ic_cl2019_65:sec7:sd", "bsp_morb_p9:sec921:scustomeridentification"],
    "q45": ["sec_mc16_2018:ch8:sec8.3", "bsp_morb_p9:sec911:sboardandseniormanagementoversight"],
    "q46": ["dnfbp2021:titleiii:sec9:sg", "dnfbp2021:titleiii:sec8", "ic_cl2018_48:titleiv:sec10"],
    "q47": ["dnfbp2021:titleiii:sec10", "bsp_morb_p9:sec911:sinternalaudit", "sec_mc16_2018:ch10:sec10.4",
            "ic_cl2018_48:titleiv:sec12"],
    "q48": ["dnfbp2021:titleiv:sec31", "ic_cl2018_48:titlev:sec37", "bsp_morb_p9:sec921:scustomeridentification",
            "bo2018:sec4:sd", "sec_mc16_2018:ch5:sec5.a.12"],
    "q49": ["ic_cl2018_48:titlev:sec44", "bsp_morb_p9:sec921:scustomeridentification", "dnfbp2021:titleiv:sec36"],
}
