# -*- coding: utf-8 -*-
import sys

fpath = r"C:\Users\Administrator\Desktop\量化AI公司\01_策略库\连连数字\实盘策略核心文件\连连数字V4策略全套文件\v4_live_engine.py"

with open(fpath, 'r', encoding='utf-8') as f:
    content = f.read()

# Fix execute_trade: place_order returns 3 values (ret_code, ret_msg, data)
old_trade = '''                    ret, data = self.trade_ctx.place_order(
                        price=signal['price'],
                        qty=qty,
                        code=self.stock_code,
                        trd_side=TrdSide.BUY,
                        order_type=OrderType.NORMAL,
                        trd_env=TrdEnv.REAL,
                        acc_id=self.acc_id
                    )
                    if ret == RET_OK:
                        self.logger.info(f"[买入成功] {qty}股 @ {signal['price']}")
                        self.current_position += qty
                        self.cash -= qty * signal['price']
                        self.daily_trades += 1
                        return True
                    else:
                        self.logger.error(f"[买入失败] {data}")
                        return False
            
            elif signal['final_sell']:
                # 卖出
                qty = min(self.trade_qty, self.current_position - self.min_position)
                if qty >= 100:
                    ret, data = self.trade_ctx.place_order(
                        price=signal['price'],
                        qty=qty,
                        code=self.stock_code,
                        trd_side=TrdSide.SELL,
                        order_type=OrderType.NORMAL,
                        trd_env=TrdEnv.REAL,
                        acc_id=self.acc_id
                    )
                    if ret == RET_OK:
                        self.logger.info(f"[卖出成功] {qty}股 @ {signal['price']}")
                        self.current_position -= qty
                        self.cash += qty * signal['price']
                        self.daily_trades += 1
                        return True
                    else:
                        self.logger.error(f"[卖出失败] {data}")'''

new_trade = '''                    ret_code, ret_msg, _ = self.trade_ctx.place_order(
                        price=signal['price'],
                        qty=qty,
                        code=self.stock_code,
                        trd_side=TrdSide.BUY,
                        order_type=OrderType.NORMAL,
                        trd_env=TrdEnv.REAL,
                        acc_id=self.acc_id
                    )
                    if ret_code == RET_OK:
                        self.logger.info(f"[买入成功] {qty}股 @ {signal['price']}")
                        self.current_position += qty
                        self.cash -= qty * signal['price']
                        self.daily_trades += 1
                        return True
                    else:
                        self.logger.error(f"[买入失败]({ret_code}): {ret_msg}")
                        return False

            elif signal['final_sell']:
                # 卖出
                qty = min(self.trade_qty, self.current_position - self.min_position)
                if qty >= 100:
                    ret_code, ret_msg, _ = self.trade_ctx.place_order(
                        price=signal['price'],
                        qty=qty,
                        code=self.stock_code,
                        trd_side=TrdSide.SELL,
                        order_type=OrderType.NORMAL,
                        trd_env=TrdEnv.REAL,
                        acc_id=self.acc_id
                    )
                    if ret_code == RET_OK:
                        self.logger.info(f"[卖出成功] {qty}股 @ {signal['price']}")
                        self.current_position -= qty
                        self.cash += qty * signal['price']
                        self.daily_trades += 1
                        return True
                    else:
                        self.logger.error(f"[卖出失败]({ret_code}): {ret_msg}")'''

if old_trade in content:
    content = content.replace(old_trade, new_trade)
    print("OK execute_trade FIXED")
else:
    print("WARN execute_trade pattern not found - may already be fixed or different formatting")

with open(fpath, 'w', encoding='utf-8') as f:
    f.write(content)

print("File saved: " + fpath)
