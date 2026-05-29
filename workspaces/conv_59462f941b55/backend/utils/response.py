from flask import jsonify

def success(data=None, message='success', code=0):
    """成功响应"""
    return jsonify({
        'code': code,
        'message': message,
        'data': data
    })

def error(message='error', code=-1, http_status=400):
    """错误响应"""
    return jsonify({
        'code': code,
        'message': message,
        'data': None
    }), http_status

def paginated_response(data, page, size, total, message='success'):
    """分页响应"""
    return jsonify({
        'code': 0,
        'message': message,
        'data': {
            'items': data,
            'page': page,
            'size': size,
            'total': total
        }
    })
