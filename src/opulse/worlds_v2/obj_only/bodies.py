"""Object invariants expressed as kernel nodes over the fixed generic vocabulary."""

from opulse.atoms import nodes as n
from opulse.atoms.values import Bottom


def lit(value):
    return n.Lit(value)


def var(name):
    return n.Var(name)


def call(name, *args):
    return n.Call(name, args)


def let(name, value, body):
    return n.Let(name, value, body)


def when(condition, yes, no=None):
    if no is None:
        no = lit(Bottom("invalid"))
    return n.Case(((n.Test(condition), yes),), no)


def both(left, right):
    return when(left, right, lit(False))


def equal(left, right):
    return call("eq", left, right)


def field(value, index):
    return call("field", value, lit(index))


def seq(*values):
    result = lit(())
    for value in reversed(values):
        result = call("cons", value, result)
    return result


def record(name, *values):
    return call("make_record", lit("raw"), lit(name), seq(*values))


def shape(value, name, count=None):
    condition = equal(call("tag", value), lit(name))
    return both(condition, equal(call("field_count", value), lit(count))) if count is not None else condition


def norm(pair):
    return let("num", field(pair, 0), let("den", field(pair, 1),
               when(equal(var("den"), lit(0)), lit(Bottom("invalid")),
                    let("divisor", call("gcd", var("num"), var("den")),
                        let("negative", call("lt", var("den"), lit(0)),
                            seq(when(var("negative"),
                                     call("neg", call("div_exact", var("num"), var("divisor"))),
                                     call("div_exact", var("num"), var("divisor"))),
                                when(var("negative"),
                                     call("neg", call("div_exact", var("den"), var("divisor"))),
                                     call("div_exact", var("den"), var("divisor")))))))))


def rat(value):
    return call("rat_parse", value)


def integer(value):
    return seq(value, lit(1))


def numerator(value):
    return field(value, 0)


def denominator(value):
    return field(value, 1)


def rat_operation(left, right, operation):
    if operation == "add":
        num = call("add", call("mul", numerator(var("left")), denominator(var("right"))),
                   call("mul", numerator(var("right")), denominator(var("left"))))
        den = call("mul", denominator(var("left")), denominator(var("right")))
    elif operation == "mul":
        num = call("mul", numerator(var("left")), numerator(var("right")))
        den = call("mul", denominator(var("left")), denominator(var("right")))
    elif operation == "div":
        num = call("mul", numerator(var("left")), denominator(var("right")))
        den = call("mul", denominator(var("left")), numerator(var("right")))
    else:
        raise ValueError(operation)
    return let("left", left, let("right", right, norm(seq(num, den))))


def radd(left, right):
    return call("rat_add", left, right)


def rmul(left, right):
    return call("rat_mul", left, right)


def rdiv(left, right):
    return call("rat_div", left, right)


def rneg(value):
    return let("rneg_value", value, seq(call("neg", numerator(var("rneg_value"))),
                                        denominator(var("rneg_value"))))


def rsub(left, right):
    return radd(left, rneg(right))


def rlt(left, right):
    return call("rat_lt", left, right)


def req(left, right):
    return call("rat_eq", left, right)


def rpow(value, exponent):
    return call("rat_pow", value, exponent)


def show(value):
    return call("rat_format", value)


def canonical(name, value):
    return field(call(f"{name}.make", value), 0)


def list_reverse(values):
    return n.Rec("reverse_items", ("remaining", "result"),
                 when(call("is_empty", var("remaining")), var("result"),
                      call("reverse_items", call("tail", var("remaining")),
                           call("cons", call("head", var("remaining")), var("result")))),
                 (values, lit(())), call("list_length", var("remaining")))


def concat(left, right):
    return n.Rec("append_items", ("append_remaining",),
                 when(call("is_empty", var("append_remaining")), right,
                      call("cons", call("head", var("append_remaining")),
                           call("append_items", call("tail", var("append_remaining"))))),
                 (left,), call("list_length", var("append_remaining")))


def last(values):
    return n.Rec("last_item", ("remaining",),
                 when(call("is_empty", call("tail", var("remaining"))),
                      call("head", var("remaining")),
                      call("last_item", call("tail", var("remaining")))),
                 (values,), call("list_length", var("remaining")))


def rat_body():
    return when(shape(var("x"), "Rat", 2),
                let("fraction", norm(seq(field(var("x"), 0), field(var("x"), 1))),
                    record("Rat", numerator(var("fraction")), denominator(var("fraction")))))


def poly_body():
    row = var("row")
    exponent = field(row, 0)
    rows = n.Rec("pack_rows", ("remaining",),
                 when(call("is_empty", var("remaining")), lit(()),
                      let("row", call("head", var("remaining")),
                          when(both(shape(row, "term", 2),
                                    both(call("lt", lit(-1), exponent),
                                         call("lt", exponent, lit(257)))),
                               call("cons", seq(exponent, norm(call("rat_parse", field(row, 1)))),
                                    call("pack_rows", call("tail", var("remaining"))))))),
                 (field(var("x"), 0),), call("list_length", var("remaining")))
    selected = when(equal(numerator(var("total")), lit(0)), var("output"),
                    call("cons", record("term", var("previous"), show(var("total"))), var("output")))
    merged = n.Rec("merge_rows", ("remaining", "previous", "total", "output"),
                   when(call("is_empty", var("remaining")), selected,
                        let("next", call("head", var("remaining")),
                            when(equal(field(var("next"), 0), var("previous")),
                                 call("merge_rows", call("tail", var("remaining")),
                                      var("previous"), radd(var("total"), field(var("next"), 1)),
                                      var("output")),
                                 call("merge_rows", call("tail", var("remaining")),
                                      field(var("next"), 0), field(var("next"), 1), selected)))),
                   (call("tail", var("sorted")), field(call("head", var("sorted")), 0),
                    field(call("head", var("sorted")), 1), lit(())),
                   call("list_length", var("remaining")))
    return when(shape(var("x"), "SparsePoly", 1),
                let("sorted", call("sort", rows),
                    record("SparsePoly", when(call("is_empty", var("sorted")), lit(()),
                                               list_reverse(merged)))))


def span_body():
    return when(shape(var("x"), "Span", 2),
                let("lo", norm(rat(field(var("x"), 0))),
                    let("hi", norm(rat(field(var("x"), 1))),
                        when(rlt(var("lo"), var("hi")),
                             record("Span", show(var("lo")), show(var("hi")))))))


def degree(source):
    return let("degree_terms", field(source, 0),
               when(call("is_empty", var("degree_terms")), lit(0),
                    field(last(var("degree_terms")), 0)))


def coefficient(source, domain, position, highest):
    term = var("coefficient_term")
    exponent = field(term, 0)
    lo = rat(field(domain, 0))
    width = rsub(rat(field(domain, 1)), lo)
    summand = rdiv(rmul(rmul(rmul(rat(field(term, 1)),
                                    integer(call("binom", exponent, var("index")))),
                               rmul(rpow(lo, call("sub", exponent, var("index"))),
                                    rpow(width, var("index")))),
                          integer(call("binom", position, var("index")))),
                   integer(call("binom", highest, var("index"))))
    inner = n.Rec("sum_powers", ("index", "total"),
                  when(call("lt", var("index"), lit(0)), var("total"),
                       when(call("lt", exponent, var("index")),
                            call("sum_powers", call("sub", var("index"), lit(1)), var("total")),
                            call("sum_powers", call("sub", var("index"), lit(1)),
                                 radd(var("total"), summand)))),
                  (position, integer(lit(0))), call("add", var("index"), lit(1)))
    return n.Rec("sum_terms", ("remaining", "total"),
                 when(call("is_empty", var("remaining")), var("total"),
                      let("coefficient_term", call("head", var("remaining")),
                          call("sum_terms", call("tail", var("remaining")),
                               radd(var("total"), inner)))),
                 (field(source, 0), integer(lit(0))), call("list_length", var("remaining")))


def patch_body():
    values = n.Rec("patch_positions", ("position",),
                   when(call("lt", var("highest"), var("position")), lit(()),
                        call("cons", show(coefficient(var("source"), var("domain"),
                                                       var("position"), var("highest"))),
                             call("patch_positions", call("add", var("position"), lit(1))))),
                   (lit(0),), call("add", call("sub", var("highest"), var("position")), lit(1)))
    return when(both(shape(var("x"), "BernsteinPatch"),
                     both(call("lt", lit(1), call("field_count", var("x"))),
                          call("lt", call("field_count", var("x")), lit(4)))),
                let("source", canonical("SparsePoly", field(var("x"), 0)),
                    let("domain", canonical("Span", field(var("x"), 1)),
                        let("highest", degree(var("source")),
                            let("coefficients", values,
                                when(equal(call("field_count", var("x")), lit(3)),
                                     when(equal(var("coefficients"), field(var("x"), 2)),
                                          record("BernsteinPatch", var("source"), var("domain"),
                                                 var("coefficients"))),
                                     record("BernsteinPatch", var("source"), var("domain"),
                                            var("coefficients"))))))))


def tile_body():
    check = n.Rec("check_signs", ("remaining",),
                  when(call("is_empty", var("remaining")), lit(True),
                       when(rlt(integer(lit(0)),
                                rmul(rat(call("head", var("remaining"))), integer(var("sign")))),
                            call("check_signs", call("tail", var("remaining"))), lit(False))),
                  (var("coefficients"),), call("list_length", var("remaining")))
    result = record("SignTile", var("source"), var("domain"), var("sign"), var("coefficients"))
    return when(both(shape(var("x"), "SignTile"),
                     both(call("lt", lit(2), call("field_count", var("x"))),
                          call("lt", call("field_count", var("x")), lit(5)))),
                let("source", canonical("SparsePoly", field(var("x"), 0)),
                    let("domain", canonical("Span", field(var("x"), 1)),
                        let("patch", canonical("BernsteinPatch",
                                               record("BernsteinPatch", var("source"), var("domain"))),
                            let("coefficients", field(var("patch"), 2),
                                let("sign", when(rlt(integer(lit(0)),
                                                         rat(call("head", var("coefficients")))),
                                                 lit(1), lit(-1)),
                                    when(both(check,
                                              both(when(equal(field(var("x"), 2), lit(0)),
                                                        lit(True), equal(field(var("x"), 2), var("sign"))),
                                                   when(equal(call("field_count", var("x")), lit(4)),
                                                        equal(field(var("x"), 3), var("coefficients")),
                                                    lit(True)))), result)))))))


def ordered(parts):
    inserted = n.Rec("insert_piece", ("rest",),
                     when(call("is_empty", var("rest")), seq(var("piece")),
                          when(rlt(rat(field(field(var("piece"), 1), 0)),
                                   rat(field(field(call("head", var("rest")), 1), 0))),
                               call("cons", var("piece"), var("rest")),
                               call("cons", call("head", var("rest")),
                                    call("insert_piece", call("tail", var("rest")))))),
                     (var("accumulator"),), call("list_length", var("rest")))
    return n.Rec("order_pieces", ("remaining", "accumulator"),
                 when(call("is_empty", var("remaining")), var("accumulator"),
                      let("piece", call("head", var("remaining")),
                          call("order_pieces", call("tail", var("remaining")), inserted))),
                 (parts, lit(())), call("list_length", var("remaining")))


def partition(source, domain, pieces, kind):
    canonical_piece = (when(equal(call("tag", var("piece")), lit("SignTile")),
                            canonical("SignTile", var("piece")),
                            canonical("RootBracket", var("piece"))) if kind == "RootAtlas" else
                       canonical("SignTile", var("piece")))
    checks = both(equal(field(var("checked"), 0), source),
                  both(req(rat(field(field(var("checked"), 1), 0)), var("boundary")),
                       when(equal(lit(kind), lit("SignCover")),
                            equal(field(var("checked"), 2), var("sign")), lit(True))))
    walker = n.Rec("check_pieces", ("remaining", "boundary", "accepted"),
                   when(call("is_empty", var("remaining")),
                        when(req(var("boundary"), rat(field(domain, 1))), var("accepted")),
                        let("piece", call("head", var("remaining")),
                            let("checked", canonical_piece,
                                when(checks,
                                     call("check_pieces", call("tail", var("remaining")),
                                          rat(field(field(var("checked"), 1), 1)),
                                          call("cons", var("checked"), var("accepted"))))))),
                   (var("sorted"), rat(field(domain, 0)), lit(())),
                   call("list_length", var("remaining")))
    return let("sorted", ordered(pieces),
               when(call("is_empty", var("sorted")), lit(Bottom("invalid")),
                    list_reverse(walker)))


def cover_body():
    return when(shape(var("x"), "SignCover", 3),
                let("source", canonical("SparsePoly", field(var("x"), 0)),
                    let("domain", canonical("Span", field(var("x"), 1)),
                        let("sign", field(canonical("SignTile", call("head", field(var("x"), 2))), 2),
                            record("SignCover", var("source"), var("domain"),
                                   partition(var("source"), var("domain"), field(var("x"), 2),
                                             "SignCover"))))))


def evaluate_poly(source, point):
    term = var("eval_term")
    expression = rmul(rat(field(term, 1)), rpow(point, field(term, 0)))
    return n.Rec("evaluate_terms", ("remaining", "total"),
                 when(call("is_empty", var("remaining")), var("total"),
                      let("eval_term", call("head", var("remaining")),
                          call("evaluate_terms", call("tail", var("remaining")),
                               radd(var("total"), expression)))),
                 (field(source, 0), integer(lit(0))), call("list_length", var("remaining")))


def derivative(source):
    term = var("derivative_term")
    rows = n.Rec("derive_terms", ("remaining",),
                 when(call("is_empty", var("remaining")), lit(()),
                      let("derivative_term", call("head", var("remaining")),
                          when(equal(field(term, 0), lit(0)),
                               call("derive_terms", call("tail", var("remaining"))),
                               call("cons", record("term", call("sub", field(term, 0), lit(1)),
                                                   show(rmul(rat(field(term, 1)),
                                                             integer(field(term, 0))))),
                                    call("derive_terms", call("tail", var("remaining"))))))),
                 (field(source, 0),), call("list_length", var("remaining")))
    return canonical("SparsePoly", record("SparsePoly", rows))


def coefficient_at(source, exponent):
    return n.Rec("find_coefficient", ("remaining",),
                 when(call("is_empty", var("remaining")), integer(lit(0)),
                      when(equal(field(call("head", var("remaining")), 0), exponent),
                           rat(field(call("head", var("remaining")), 1)),
                           call("find_coefficient", call("tail", var("remaining"))))),
                 (field(source, 0),), call("list_length", var("remaining")))


def divide_linear(source, root):
    highest = degree(source)
    division = n.Rec("divide_coefficients", ("exponent", "carry", "rows"),
                     when(equal(var("exponent"), lit(0)),
                          when(req(radd(coefficient_at(source, lit(0)),
                                        rmul(root, var("carry"))), integer(lit(0))),
                               canonical("SparsePoly", record("SparsePoly", var("rows")))),
                          let("next_coefficient", radd(coefficient_at(source, var("exponent")),
                                                       rmul(root, var("carry"))),
                              call("divide_coefficients", call("sub", var("exponent"), lit(1)),
                                   var("next_coefficient"),
                                   call("cons", record("term", call("sub", var("exponent"), lit(1)),
                                                       show(var("next_coefficient"))), var("rows"))))),
                     (call("add", highest, lit(0)), integer(lit(0)), lit(())), var("exponent"))
    return when(call("lt", lit(0), highest), division)


def witness_tiles(source, domain):
    midpoint = rdiv(radd(rat(field(var("current"), 0)),
                           rat(field(var("current"), 1))), integer(lit(2)))
    left = record("Span", field(var("current"), 0), show(midpoint))
    right = record("Span", show(midpoint), field(var("current"), 1))
    return n.Rec("subdivide", ("current", "remaining"),
                 let("candidate", record("SignTile", source, var("current"), lit(0)),
                     when(call("is_ok", canonical("SignTile", var("candidate"))),
                          seq(canonical("SignTile", var("candidate"))),
                          when(equal(var("remaining"), lit(0)), call("bounded_count", lit(-1)),
                               concat(call("subdivide", left, call("sub", var("remaining"), lit(1))),
                                      call("subdivide", right, call("sub", var("remaining"), lit(1))))))),
                 (domain, lit(20)), var("remaining"))


def root_body():
    root = var("root")
    source = var("source")
    domain = var("domain")
    multiplicity = var("multiplicity")
    repeated = n.Rec("divide_repeatedly", ("quotient", "remaining"),
                     when(equal(var("remaining"), lit(0)), var("quotient"),
                          call("divide_repeatedly", divide_linear(var("quotient"), rat(root)),
                               call("sub", var("remaining"), lit(1)))),
                     (source, call("add", multiplicity, lit(0))), var("remaining"))
    left_sign = evaluate_poly(source, rat(field(domain, 0)))
    right_sign = evaluate_poly(source, rat(field(domain, 1)))
    simple_check = both(
        when(req(var("left_value"), integer(lit(0))), lit(False), lit(True)),
        both(when(req(var("right_value"), integer(lit(0))), lit(False), lit(True)),
             when(rlt(var("left_value"), integer(lit(0))),
                  rlt(integer(lit(0)), var("right_value")),
                  rlt(var("right_value"), integer(lit(0))))))
    source_witness = when(equal(root, lit("")), derivative(source),
                          let("quotient", repeated,
                              when(req(evaluate_poly(var("quotient"), rat(root)), integer(lit(0))),
                                   lit(Bottom("invalid")), var("quotient"))))
    tiles = when(call("is_empty", field(var("x"), 4)),
                 witness_tiles(var("witness_source"), domain),
                 n.Rec("witness_rows", ("remaining",),
                       when(call("is_empty", var("remaining")), lit(()),
                            let("row", call("head", var("remaining")),
                                when(shape(var("row"), "witness", 3),
                                     call("cons", record("SignTile", var("witness_source"),
                                                         record("Span", field(var("row"), 0),
                                                                field(var("row"), 1)),
                                                         field(var("row"), 2)),
                                          call("witness_rows", call("tail", var("remaining"))))))),
                       (field(var("x"), 4),), call("list_length", var("remaining"))))
    canonical_witness = n.Rec("encode_witness", ("remaining",),
                              when(call("is_empty", var("remaining")), lit(()),
                                   let("piece", call("head", var("remaining")),
                                       call("cons", record("witness", field(field(var("piece"), 1), 0),
                                                           field(field(var("piece"), 1), 1),
                                                           field(var("piece"), 2)),
                                            call("encode_witness", call("tail", var("remaining")))))),
                              (field(var("cover"), 2),), call("list_length", var("remaining")))
    proof = let("witness_source", source_witness,
                let("cover", canonical("SignCover", record("SignCover", var("witness_source"),
                                                        domain, tiles)),
                    let("witness", canonical_witness,
                        when(both(when(equal(root, lit("")),
                                       equal(field(call("head", field(var("cover"), 2)), 2),
                                             when(rlt(var("left_value"), integer(lit(0))),
                                                  lit(1), lit(-1))), lit(True)),
                                  when(call("is_empty", field(var("x"), 4)), lit(True),
                                       equal(field(var("x"), 4), var("witness")))),
                                  record("RootBracket", source, domain, root, multiplicity,
                                         var("witness"))))))
    exact_check = both(call("lt", lit(1), multiplicity),
                       both(rlt(rat(field(domain, 0)), rat(root)),
                            rlt(rat(root), rat(field(domain, 1)))))
    return when(shape(var("x"), "RootBracket", 5),
                let("source", canonical("SparsePoly", field(var("x"), 0)),
                    let("domain", canonical("Span", field(var("x"), 1)),
                        let("root", when(equal(field(var("x"), 2), lit("")), lit(""),
                                         show(norm(rat(field(var("x"), 2))))),
                            let("multiplicity", field(var("x"), 3),
                                when(equal(root, lit("")),
                                     when(equal(multiplicity, lit(1)),
                                          let("left_value", left_sign,
                                              let("right_value", right_sign,
                                                  when(simple_check, proof)))),
                                     when(exact_check, proof)))))))


def atlas_body():
    return when(shape(var("x"), "RootAtlas", 3),
                let("source", canonical("SparsePoly", field(var("x"), 0)),
                    let("domain", canonical("Span", field(var("x"), 1)),
                        record("RootAtlas", var("source"), var("domain"),
                               partition(var("source"), var("domain"), field(var("x"), 2),
                                         "RootAtlas")))))


def body(name):
    return {"Rat": rat_body, "SparsePoly": poly_body, "Span": span_body,
            "BernsteinPatch": patch_body, "SignTile": tile_body, "SignCover": cover_body,
            "RootBracket": root_body, "RootAtlas": atlas_body}[name]()
