def compute_zones(profile: dict):
    w, h = profile["video"]["size"]
    z = profile["layout"]["zones"]
    def box(y0, y1):
        return (0, int(h*y0), w, int(h*y1))
    return {
        "stock": box(z["stock"]["y0"], z["stock"]["y1"]),
        "subs": box(z["subs"]["y0"], z["subs"]["y1"]),
        "persona": (0, int(h*z["persona"]["y0"]), w, h)
    }
