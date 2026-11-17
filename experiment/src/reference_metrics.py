"""Small, offline, standard-library reference calculations.

No API calls, model downloads, or implicit exclusion of failed trajectories.
These functions do not establish the validity of the input annotations.
"""
from __future__ import annotations

import collections
import itertools
import json
import math
import random
import re
import statistics


def safe_ratio(numerator, denominator):
    if denominator == 0:
        return None
    return numerator / denominator


def levenshtein(left, right):
    row = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        new = [i]
        for j, b in enumerate(right, 1):
            new.append(min(new[-1] + 1, row[j] + 1, row[j-1] + (a != b)))
        row = new
    return row[-1]


def normalized_edit(left, right):
    if left is None or right is None or len(left) == 0 or len(right) == 0:
        raise ValueError("Invalid/empty output is not an ordinary structural sequence")
    return levenshtein(left, right) / max(len(left), len(right))


def mean_pairwise_edit(sequences, expected_k=3):
    if len(sequences) != expected_k:
        raise ValueError("Trajectory count changed; do not silently change the denominator")
    if any(x is None or len(x) == 0 for x in sequences):
        return None
    return statistics.mean(normalized_edit(a, b) for a, b in itertools.combinations(sequences, 2))


def mean_adjacent_edit(previous, current, expected_k=3):
    if len(previous) != expected_k or len(current) != expected_k:
        raise ValueError("Expected the frozen number of aligned trajectories")
    if any(x is None or len(x) == 0 for x in previous + current):
        return None
    return statistics.mean(normalized_edit(a, b) for a, b in zip(previous, current))


def contraction(d0, dt):
    return None if d0 is None or dt is None else d0 - dt


def extra_contraction(loop0, loopt, independent0, independentt):
    if any(x is None for x in [loop0, loopt, independent0, independentt]):
        return None
    return (loop0 - loopt) - (independent0 - independentt)


def shared_baseline_bounds(loop_final, independent_final):
    """Bounds for delta = D_independent(T) - D_loop(T), not for D itself."""
    for value in [loop_final, independent_final]:
        if value is not None and not (0 <= value <= 1):
            raise ValueError("Distance must be in [0,1]")
    l_low, l_high = (0, 1) if loop_final is None else (loop_final, loop_final)
    i_low, i_high = (0, 1) if independent_final is None else (independent_final, independent_final)
    return i_low - l_high, i_high - l_low


def mean_absolute_pairwise(values, expected_k=3):
    if len(values) != expected_k:
        raise ValueError("Changed trajectory denominator")
    if any(x is None for x in values):
        return None
    return statistics.mean(abs(a-b) for a, b in itertools.combinations(values, 2))


def cosine(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("Nonempty equal-dimensional vectors required")
    if any(not math.isfinite(x) for x in list(left)+list(right)):
        raise ValueError("Embedding values must be finite")
    nl = math.hypot(*left); nr = math.hypot(*right)
    if nl == 0 or nr == 0:
        raise ValueError("Zero vector is not a valid embedding")
    value=sum((a/nl)*(b/nr) for a,b in zip(left,right))
    if not math.isfinite(nl) or not math.isfinite(nr) or not math.isfinite(value):
        raise ValueError("Cosine calculation must be finite")
    return max(-1.0,min(1.0,value))


def jaccard_distance(left, right):
    left, right = set(left), set(right)
    union = left | right
    return None if not union else 1 - len(left & right) / len(union)


def issue_dynamics(history):
    """history contains active concern identity sets only, not withdrawn mentions."""
    all_seen = set(); result = []
    for t, values in enumerate(history):
        current = set(values)
        if t == 0:
            result.append({"initial": sorted(current), "new": None, "returned": None})
        else:
            result.append({"initial": None, "new": sorted(current - all_seen),
                           "returned": sorted((current & all_seen) - set(history[t-1]))})
        all_seen |= current
    return result


def itf_idf(reviews, threshold=0.5, expected_reviews=6):
    """reviews: one review per different paper, each a list of segment vectors."""
    if len(reviews) != expected_reviews:
        raise ValueError("Cross-paper pool size changed")
    if not 0 < threshold <= 1:
        raise ValueError("Use a positive, development-frozen similarity threshold")
    if any(review is None or not review for review in reviews):
        return None
    m = len(reviews); scores = []
    for review in reviews:
        n = len(review); per_segment = []
        for segment in review:
            own = [cosine(segment, other) for other in review]
            occurrence = sum(x for x in own if x >= threshold)
            per_review = [max(cosine(segment, other) for other in r) for r in reviews]
            review_occurrence = sum(x for x in per_review if x >= threshold)
            if occurrence <= 0 or review_occurrence <= 0:
                raise ValueError("Self match must be included and positive")
            per_segment.append(math.log(n / occurrence) * math.log(m / review_occurrence))
        scores.append(statistics.mean(per_segment))
    return statistics.mean(scores)


def _symmetric_eigenvalues(matrix, tolerance=1e-12, max_sweeps=200):
    """Jacobi solver for small audit matrices; raises rather than accepting nonconvergence."""
    n = len(matrix)
    if not n or any(len(row) != n for row in matrix):
        raise ValueError("Nonempty square matrix required")
    a = [[float(x) for x in row] for row in matrix]
    if any(not math.isfinite(x) for row in a for x in row):
        raise ValueError("Finite matrix required")
    if any(abs(a[i][j]-a[j][i]) > tolerance*10 for i in range(n) for j in range(n)):
        raise ValueError("Symmetric matrix required")
    if n == 1:
        return [a[0][0]]
    for _ in range(max_sweeps * n*n):
        p, q = max(itertools.combinations(range(n), 2), key=lambda pair: abs(a[pair[0]][pair[1]]))
        if abs(a[p][q]) < tolerance:
            return [a[i][i] for i in range(n)]
        apq = a[p][q]
        tau = (a[q][q]-a[p][p]) / (2*apq)
        t = math.copysign(1.0, tau) / (abs(tau)+math.sqrt(1+tau*tau)) if tau else 1.0
        c = 1/math.sqrt(1+t*t); s = t*c
        app, aqq = a[p][p], a[q][q]
        a[p][p] = app - t*apq; a[q][q] = aqq + t*apq
        a[p][q] = a[q][p] = 0.0
        for k in range(n):
            if k in (p, q):
                continue
            akp, akq = a[k][p], a[k][q]
            a[k][p] = a[p][k] = c*akp - s*akq
            a[k][q] = a[q][k] = s*akp + c*akq
    raise ValueError("Jacobi solver did not converge")


def vendi_score(kernel, psd_tolerance=1e-8):
    n = len(kernel)
    if not n or any(len(row) != n for row in kernel):
        raise ValueError("Square nonempty kernel required")
    if any(abs(kernel[i][i]-1.0) > psd_tolerance for i in range(n)):
        raise ValueError("Kernel must have unit diagonal")
    eigenvalues = _symmetric_eigenvalues(kernel)
    if min(eigenvalues) < -psd_tolerance:
        raise ValueError("Non-PSD matrix; do not use arbitrary text similarity as a Vendi kernel")
    lambdas = [max(0.0, x)/n for x in eigenvalues]
    total = sum(lambdas)
    if abs(total-1.0) > psd_tolerance*10:
        raise ValueError("Normalized kernel spectrum must sum to one")
    lambdas = [x/total for x in lambdas]
    return math.exp(-sum(x*math.log(x) for x in lambdas if x > 0))


def wl_features(graph, iterations=2):
    """Typed directed WL feature map. Node IDs never appear in feature labels."""
    nodes = graph["nodes"]; edges = graph["edges"]
    if len({x["id"] for x in nodes}) != len(nodes):
        raise ValueError("Duplicate graph node")
    labels = {x["id"]: str(x["label"]) for x in nodes}
    if not labels:
        raise ValueError("Empty structural graph")
    for source, target, edge_type in edges:
        if source not in labels or target not in labels:
            raise ValueError("Unknown edge endpoint")
    counts = collections.Counter()
    for h in range(iterations+1):
        counts.update((h, label) for label in labels.values())
        if h == iterations:
            break
        new_labels = {}
        for node in labels:
            neighborhood = []
            for source, target, edge_type in edges:
                if source == node:
                    neighborhood.append(("out", edge_type, labels[target]))
                if target == node:
                    neighborhood.append(("in", edge_type, labels[source]))
            new_labels[node] = json.dumps([labels[node], sorted(neighborhood)], ensure_ascii=False, separators=(",", ":"))
        labels = new_labels
    return dict(counts)


def feature_cosine(left, right):
    keys = sorted(set(left) | set(right), key=str)
    return cosine([left.get(k, 0) for k in keys], [right.get(k, 0) for k in keys])


def classification_report(gold, predicted, labels):
    if len(gold) != len(predicted):
        raise ValueError("Gold/prediction length mismatch")
    label_set = set(labels)
    unknown_gold = sum(x not in label_set for x in gold)
    eligible = [(g,p) for g,p in zip(gold,predicted) if g in label_set]
    evaluated = [(g,p) for g,p in eligible if p in label_set]
    per_class = {}
    for label in labels:
        tp = sum(g == label and p == label for g,p in evaluated)
        fp = sum(g != label and p == label for g,p in evaluated)
        fn = sum(g == label and p != label for g,p in evaluated)
        tn = sum(g != label and p != label for g,p in evaluated)
        precision = safe_ratio(tp, tp+fp); recall = safe_ratio(tp,tp+fn)
        f1 = safe_ratio(2*tp, 2*tp+fp+fn)
        per_class[label] = dict(tp=tp,fp=fp,fn=fn,tn=tn,precision=precision,recall=recall,
                                f1=f1,fpr=safe_ratio(fp,fp+tn),fnr=safe_ratio(fn,fn+tp))
    return {"per_class":per_class,"n_gold_eligible":len(eligible),"n_evaluated":len(evaluated),
            "gold_unknown":unknown_gold,"prediction_abstentions":len(eligible)-len(evaluated),
            "coverage":safe_ratio(len(evaluated),len(eligible)),
            "conditional_on_nonabstention":True,
            "agreement":safe_ratio(sum(g==p for g,p in evaluated),len(evaluated))}


def cohens_kappa(left, right):
    if len(left) != len(right) or not left:
        raise ValueError("Matched nonempty annotations required")
    n = len(left); classes = set(left) | set(right)
    observed = sum(a==b for a,b in zip(left,right))/n
    lc, rc = collections.Counter(left), collections.Counter(right)
    expected = sum(lc[c]*rc[c] for c in classes)/(n*n)
    return None if math.isclose(expected,1.0) else (observed-expected)/(1-expected)


def retained_bounds(retained, unassessable, total):
    if any(x < 0 for x in [retained,unassessable,total]) or retained+unassessable > total:
        raise ValueError("Invalid content counts")
    if total == 0:
        return None
    return retained/total, (retained+unassessable)/total


def qa_coverage(checks, fixed_question_ids):
    """Fixed denominator for Q32; separate comparable denominator for Q51."""
    ids=list(fixed_question_ids)
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate frozen question IDs")
    by_id={}
    for row in checks:
        qid=row["question_id"]
        if qid in by_id or qid not in set(ids):
            raise ValueError("Duplicate or unknown QA annotation ID")
        if row["baseline_in_scope"] is not True:
            raise ValueError("Evaluator cannot change the frozen baseline denominator")
        if row["anchor_state"] not in {"retained_equivalent","missing","changed","uncertain"}:
            raise ValueError("Unknown anchor state")
        if row["anchor_state"] in {"missing","changed"} and row["supported_in_text"] is True:
            raise ValueError("Missing or changed anchor cannot have confirmed equivalent text support")
        by_id[qid]=row
    fixed=[by_id.get(qid,{"question_id":qid,"baseline_in_scope":True,"anchor_state":"uncertain",
                         "answer_correct":None,"supported_in_text":None}) for qid in ids]
    comparable = [x for x in fixed if x["anchor_state"] == "retained_equivalent"]
    def good(x):
        return x["anchor_state"] == "retained_equivalent" and x["answer_correct"] is True and x["supported_in_text"] is True
    covered=sum(good(x) for x in fixed)
    possible=sum(x["anchor_state"] in {"retained_equivalent","uncertain"} and x["answer_correct"] is not False and x["supported_in_text"] is not False for x in fixed)
    return {"fixed_n":len(fixed),"covered_n":covered,
            "information_coverage":safe_ratio(covered,len(fixed)),
            "information_coverage_lower":safe_ratio(covered,len(fixed)),
            "information_coverage_upper":safe_ratio(possible,len(fixed)),
            "expression_comparable_n":len(comparable),
            "expression_comparable_coverage":safe_ratio(len(comparable),len(fixed)),
            "conditional_expression_accuracy":safe_ratio(sum(good(x) for x in comparable),len(comparable)),
            "unknown_n":sum(x["anchor_state"] == "uncertain" or x["answer_correct"] is None or x["supported_in_text"] is None for x in fixed),
            "missing_annotation_n":len(ids)-len(by_id)}


def public_question_projection(private_questions):
    """Strict allowlist: never pass gold answers or anchor text to respondents."""
    result = []
    for question in private_questions:
        result.append({k: question[k] for k in ["question_id","question","task"]})
    return result


def assert_public_questions(public_questions):
    seen=set()
    for question in public_questions:
        if set(question) != {"question_id","question","task"}:
            raise ValueError("Question payload leaks private fields or lacks public fields")
        if any(not isinstance(question[k],str) or not question[k].strip() for k in question):
            raise ValueError("Public question fields must be nonempty strings")
        if question["task"] not in {"understanding","location"} or question["question_id"] in seen:
            raise ValueError("Public question task or unique ID is invalid")
        seen.add(question["question_id"])
    return True


def assert_evidence_ids(ids, allowed_ids):
    if not set(ids) <= set(allowed_ids):
        raise ValueError("Annotation cites an evidence ID not supplied to this job")


def assert_quotes(quotes, appropriate_source_text):
    if any(not isinstance(quote,str) or not quote.strip() or quote not in appropriate_source_text for quote in quotes):
        raise ValueError("Annotation quote must be nonempty and an exact source substring")


def assert_scientific_evidence(label, quotes, source_text, evidence_ids, allowed_evidence_ids):
    """Check presence and provenance only; a qualified reviewer must assess sufficiency."""
    assert_quotes(quotes,source_text)
    assert_evidence_ids(evidence_ids,allowed_evidence_ids)
    if label in {"verified_correct","verified_error","supported","valid_added","valid","invalid"} and not quotes and not evidence_ids:
        raise ValueError("Strong scientific label requires actual quoted or whitelisted verification evidence")


def assert_blind_id(actual, expected):
    if not isinstance(expected,str) or not expected.strip() or actual != expected:
        raise ValueError("Blind manuscript ID must match the input exactly")


def map_output_status(status):
    allowed={"success","truncated","empty","refusal","off_task","parse_failure","uncertain"}
    if status not in allowed:
        raise ValueError("Unknown P27 classification")
    return "unresolved_status" if status == "uncertain" else status


def cluster_mean_interval(paper_effects, draws=5000, seed=20261117):
    values = list(paper_effects.values())
    if not values or any(x is None or not math.isfinite(x) for x in values):
        raise ValueError("Use a declared complete paper block; report exclusions separately")
    rng = random.Random(seed); n = len(values)
    samples = sorted(statistics.mean(rng.choice(values) for _ in range(n)) for _ in range(draws))
    def quantile(q):
        pos = q*(len(samples)-1); low = int(pos); high = math.ceil(pos)
        return samples[low]+(samples[high]-samples[low])*(pos-low)
    return {"mean":statistics.mean(values),"low":quantile(0.025),"high":quantile(0.975),
            "n_papers":n,"draws":draws,"seed":seed,"interpretation":"pilot_descriptive_cluster_bootstrap"}


def holm_adjust(pvalues):
    n = len(pvalues); order = sorted(range(n), key=lambda i:pvalues[i]); adjusted = [None]*n
    running = 0.0
    for rank,index in enumerate(order):
        if not 0 <= pvalues[index] <= 1:
            raise ValueError("Invalid p-value")
        running = max(running, (n-rank)*pvalues[index])
        adjusted[index] = min(1.0,running)
    return adjusted


def parse_markdown_blocks(text, document_id="DOC"):
    """Frozen lightweight parser; PDF conversion must be human checked first.

    Supports headings, paragraphs, list items, fenced code, $$ math, and pipe tables.
    Tabs are not silently expanded because offsets refer to original Unicode text.
    Input with tabs in list indentation must be normalized before hash freezing.
    """
    lines = text.splitlines(keepends=True); starts=[]; position=0
    for line in lines:
        starts.append(position); position += len(line)
    blocks=[]; heading_stack=[]; i=0
    heading_re=re.compile(r"^(#{1,6})\s+")
    list_re=re.compile(r"^( *)(?:[-+*]|\d+[.)])\s+")
    while i < len(lines):
        if not lines[i].strip():
            i += 1; continue
        line=lines[i]; begin=i; kind="paragraph"; level=None; depth=0
        heading=heading_re.match(line); bullet=list_re.match(line)
        stripped=line.strip()
        if heading:
            kind="heading"; level=len(heading.group(1)); i+=1
        elif stripped.startswith("```") or stripped.startswith("~~~"):
            kind="code"; fence=stripped[:3]; i+=1
            while i < len(lines):
                if lines[i].strip().startswith(fence):
                    i+=1; break
                i+=1
        elif stripped.startswith("$$"):
            kind="math"; i+=1
            if stripped != "$$" and stripped.endswith("$$"):
                pass
            else:
                while i < len(lines):
                    if lines[i].strip().endswith("$$"):
                        i+=1; break
                    i+=1
        elif stripped.startswith("|"):
            kind="table"; i+=1
            while i < len(lines) and lines[i].strip().startswith("|"):
                i+=1
        else:
            if bullet:
                kind="list_item"; indent=len(bullet.group(1))
                if indent % 2:
                    raise ValueError("List indentation must use multiples of two spaces before input freeze")
                depth=indent//2+1
            elif line.startswith("\t"):
                raise ValueError("Normalize tab indentation before input freeze")
            i+=1
            while i < len(lines) and lines[i].strip():
                nxt=lines[i]; ns=nxt.strip()
                if heading_re.match(nxt) or list_re.match(nxt) or ns.startswith(("```","~~~","$$","|")):
                    break
                i+=1
        start=starts[begin]; end=starts[i] if i < len(lines) else len(text)
        while end > start and text[end-1] in "\r\n":
            end-=1
        block_id=f"B{len(blocks)+1:04d}"
        if kind == "heading":
            while heading_stack and heading_stack[-1][0] >= level:
                heading_stack.pop()
            path=[bid for _,bid in heading_stack]
        else:
            path=[bid for _,bid in heading_stack]
        block=dict(document_id=document_id,block_id=block_id,block_type=kind,start=start,end=end,
                   text=text[start:end],role=None,heading_path=path,list_depth=depth,heading_level=level)
        blocks.append(block)
        if kind == "heading":
            heading_stack.append((level,block_id))
    return blocks


def body_roles(blocks, document_kind):
    allowed = set("SPNQAVMO") if document_kind == "review" else set("IBMTERDXO")
    sequence=[]
    for block in blocks:
        if block["block_type"] == "heading":
            if block.get("role") is not None:
                raise ValueError("Heading cannot enter the primary body role sequence")
            continue
        if block.get("role") not in allowed:
            raise ValueError("Missing or invalid body role; do not silently replace with O")
        sequence.append(block["role"])
    return sequence


def graph_from_blocks(blocks):
    nodes=[]; edges=[]; previous_body=None
    for block in blocks:
        bid=block["block_id"]
        if block["block_type"] == "heading":
            label="H"+str(block["heading_level"])
        else:
            if block.get("role") is None:
                raise ValueError("Roles must be annotated before graph construction")
            label="ROLE:"+block["role"]
            if previous_body:
                edges.append((previous_body,bid,"next"))
            previous_body=bid
        nodes.append({"id":bid,"label":label})
        if block["heading_path"]:
            edges.append((block["heading_path"][-1],bid,"parent"))
    return {"nodes":nodes,"edges":edges}


def render_prompt(template, parameters):
    variables=set(re.findall(r"\{\{([a-z_]+)\}\}",template))
    if variables != set(parameters):
        raise ValueError(f"Expected {sorted(variables)}, got {sorted(parameters)}")
    if "public_questions_json" in parameters:
        payload=parameters["public_questions_json"]
        assert_public_questions(json.loads(payload) if isinstance(payload,str) else payload)
    def replacement(match):
        value=parameters[match.group(1)]
        return value if isinstance(value,str) else json.dumps(value,ensure_ascii=False)
    return re.sub(r"\{\{([a-z_]+)\}\}",replacement,template)


def metadata_preflight(config, phase="generation"):
    required=config["runtime_required_before_"+phase]
    missing=[]
    for key in required:
        value=config
        for part in key.split("."):
            value=value.get(part) if isinstance(value,dict) else None
        if value is None or value == [] or value == "":
            missing.append(key)
    if phase == "generation":
        generation=config["generation"]
        if generation.get("reviewer_model_snapshot") != generation.get("writer_model_snapshot"):
            missing.append("default requires identical reviewer/writer snapshot; register a protocol variant otherwise")
        if len(config["development_papers"]) != config["development_n"] or len(config["pilot_papers"]) != config["pilot_n"]:
            missing.append("paper counts do not match the frozen configuration")
        identities={}
        for group in ["development_papers","pilot_papers"]:
            paper_ids=[]; research_ids=[]
            for paper in config[group]:
                if isinstance(paper,str):
                    pid=paper.strip(); rid=pid
                elif isinstance(paper,dict):
                    pid=paper.get("paper_id"); rid=paper.get("research_id",pid)
                    pid=pid.strip() if isinstance(pid,str) else ""
                    rid=rid.strip() if isinstance(rid,str) else ""
                else:
                    pid=rid=""
                if not pid or not rid:
                    missing.append(group+": invalid paper_id/research_id")
                paper_ids.append(pid); research_ids.append(rid)
            if len(set(paper_ids)) != len(paper_ids) or len(set(research_ids)) != len(research_ids):
                missing.append(group+": duplicate paper or research identity")
            identities[group]=(set(paper_ids),set(research_ids))
        dev,pilot=identities["development_papers"],identities["pilot_papers"]
        if (dev[0]&pilot[0]) or (dev[1]&pilot[1]):
            missing.append("development and pilot must have disjoint paper and research identities")
        if config["budget"].get("hard_cap") is not None and config["budget"]["hard_cap"] <= 0:
            missing.append("hard_cap must be positive")
    return {"ready":not missing,"missing_or_invalid":missing,"network_calls_made":False}


def runtime_preflight(config, phase="generation", activation_context=None):
    from activation_contracts import guarded_preflight
    return guarded_preflight(config,phase,metadata_preflight(config,phase),activation_context)
