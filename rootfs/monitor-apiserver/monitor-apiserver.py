import requests
import os
import time
import json
from datetime import datetime, timedelta
from typing import Optional, List
class K8sAPIMonitor:
    def __init__(self, duration_minutes: int = 5, interval_seconds: int = 10):
        """
        初始化监控器
        
        Args:
            duration_minutes: 监控持续时间（分钟）
            interval_seconds: 每个API请求间隔时间（秒）
        """
        self.duration_minutes = duration_minutes
        self.interval_seconds = interval_seconds
        self.token_path = "/var/run/secrets/kubernetes.io/serviceaccount/token"
        self.ca_cert_path = "/var/run/secrets/kubernetes.io/serviceaccount/ca.crt"
        self.log_file = f"apiserver_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        
        # API URLs 列表
        self.api_urls = [
            "https://10.43.0.1:443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.101:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.102:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.105:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.106:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.107:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.108:6443/api/v1/namespaces/ai-gateway",
            "https://10.1.104.111:6443/api/v1/namespaces/ai-gateway",
        ]
        
        # 统计信息（按URL）
        self.stats = {url: {"success": 0, "fail": 0, "total": 0} for url in self.api_urls}
        
    def load_token(self) -> Optional[str]:
        """加载 Kubernetes token"""
        try:
            with open(self.token_path, 'r') as f:
                return f.read().strip()
        except Exception as e:
            self.write_log(f"ERROR: 无法读取 token: {str(e)}")
            return None
    
    def write_log(self, message: str, print_console: bool = True):
        """写入日志文件"""
        if print_console:
            print(message)
        
        try:
            with open(self.log_file, 'a', encoding='utf-8') as f:
                f.write(message + '\n')
        except Exception as e:
            print(f"写入日志文件失败: {str(e)}")
    
    def simplify_response(self, response_data: any, max_length: int = 100) -> str:
        """
        简化响应体
        
        Args:
            response_data: 响应数据
            max_length: 最大长度
        """
        try:
            if isinstance(response_data, dict):
                # 提取关键信息
                if 'metadata' in response_data and 'name' in response_data['metadata']:
                    name = response_data['metadata']['name']
                    kind = response_data.get('kind', 'Unknown')
                    status = response_data.get('status', {})
                    phase = status.get('phase', 'N/A') if isinstance(status, dict) else 'N/A'
                    return f"kind={kind}, name={name}, phase={phase}"
                else:
                    # 如果没有标准结构，返回简化的 JSON
                    simplified = json.dumps(response_data, ensure_ascii=False)
                    if len(simplified) > max_length:
                        return simplified[:max_length] + "..."
                    return simplified
            else:
                # 非字典类型，直接转字符串并截断
                response_str = str(response_data)
                if len(response_str) > max_length:
                    return response_str[:max_length] + "..."
                return response_str
        except Exception:
            return "解析响应失败"
    
    def call_api(self, api_url: str, headers: dict, verify_path: str) -> dict:
        """
        调用 API 接口
        
        Returns:
            包含状态信息的字典
        """
        try:
            response = requests.get(
                api_url,
                headers=headers,
                verify=verify_path if os.path.exists(verify_path) else False,
                timeout=10
            )
            
            # 尝试解析 JSON
            try:
                response_data = response.json()
            except:
                response_data = response.text
            
            return {
                "success": True,
                "status_code": response.status_code,
                "response": response_data,
                "elapsed": response.elapsed.total_seconds()
            }
            
        except requests.exceptions.Timeout:
            return {
                "success": False,
                "error": "Timeout",
                "error_type": "Timeout"
            }
        except requests.exceptions.ConnectionError as e:
            error_msg = str(e)
            # 简化常见错误信息
            if "Connection refused" in error_msg:
                error_msg = "Connection refused"
            elif "Name or service not known" in error_msg:
                error_msg = "DNS resolution failed"
            else:
                error_msg = error_msg[:50]
            
            return {
                "success": False,
                "error": error_msg,
                "error_type": "ConnectionError"
            }
        except requests.exceptions.RequestException as e:
            return {
                "success": False,
                "error": f"{str(e)[:50]}",
                "error_type": "RequestException"
            }
        except Exception as e:
            return {
                "success": False,
                "error": f"{str(e)[:50]}",
                "error_type": "UnknownError"
            }
    
    def format_one_line_log(self, api_url: str, result: dict, request_count: int) -> str:
        """格式化为单行日志"""
        timestamp = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        
        # 简化 URL 显示（只显示 IP 和端口）
        try:
            url_parts = api_url.replace('https://', '').split('/')
            host_port = url_parts[0]  # 例如: 10.43.0.1:443
        except:
            host_port = api_url
        
        if result["success"]:
            status_code = result['status_code']
            elapsed = result['elapsed']
            response_summary = self.simplify_response(result['response'])
            
            # 成功日志格式
            log = (
                f"[{timestamp}] "
                f"#{request_count:04d} | "
                f"{host_port:30s} | "
                f"✓ {status_code:3d} | "
                f"{elapsed:6.3f}s | "
                f"{response_summary}"
            )
        else:
            error_type = result['error_type']
            error_msg = result['error']
            
            # 失败日志格式
            log = (
                f"[{timestamp}] "
                f"#{request_count:04d} | "
                f"{host_port:30s} | "
                f"✗ {error_type:18s} | "
                f"{error_msg}"
            )
        
        return log
    
    def print_header(self):
        """打印日志头部"""
        header = (
            f"\n{'='*130}\n"
            f"开始监控 Kubernetes API\n"
            f"监控 {len(self.api_urls)} 个 API 端点\n"
            f"监控时长: {self.duration_minutes} 分钟\n"
            f"请求间隔: {self.interval_seconds} 秒/API\n"
            f"日志文件: {self.log_file}\n"
            f"{'='*130}\n"
        )
        self.write_log(header)
        
        # 打印列标题
        column_header = (
            f"{'时间':^19} | "
            f"{'序号':^4} | "
            f"{'主机地址':^30} | "
            f"{'状态':^10} | "
            f"{'响应时间':^8} | "
            f"响应摘要"
        )
        self.write_log(column_header)
        self.write_log("-" * 130)
    
    def print_summary(self, total_request_count: int, total_success_count: int, total_fail_count: int):
        """打印统计摘要"""
        self.write_log("\n" + "="*130)
        self.write_log("监控完成 - 总体统计:")
        self.write_log(f"  总请求次数: {total_request_count}")
        self.write_log(f"  成功次数: {total_success_count} ({(total_success_count/total_request_count*100):.2f}%)" if total_request_count > 0 else "  成功次数: 0")
        self.write_log(f"  失败次数: {total_fail_count} ({(total_fail_count/total_request_count*100):.2f}%)" if total_request_count > 0 else "  失败次数: 0")
        
        self.write_log("\n各 API 端点统计:")
        self.write_log(f"{'主机地址':^35} | {'总请求':>8} | {'成功':>8} | {'失败':>8} | {'成功率':>10}")
        self.write_log("-" * 130)
        
        for url in self.api_urls:
            stats = self.stats[url]
            # 提取主机端口
            try:
                host_port = url.replace('https://', '').split('/')[0]
            except:
                host_port = url
            
            total = stats['total']
            success = stats['success']
            fail = stats['fail']
            success_rate = (success / total * 100) if total > 0 else 0
            
            self.write_log(
                f"{host_port:^35} | {total:8d} | {success:8d} | {fail:8d} | {success_rate:9.2f}%"
            )
        
        self.write_log(f"\n日志文件: {self.log_file}")
        self.write_log("="*130 + "\n")
    
    def run(self, target_urls: Optional[List[str]] = None):
        """
        运行监控
        
        Args:
            target_urls: 指定要监控的 API URL 列表，如果为 None 则使用所有 URL
        """
        # 加载 token
        token = self.load_token()
        if not token:
            self.write_log("ERROR: Token 加载失败，程序退出")
            return
        
        headers = {"Authorization": f"Bearer {token}"}
        
        # 确定要监控的 URL 列表
        urls_to_monitor = target_urls or self.api_urls
        
        # 重新初始化统计信息（如果是自定义URL列表）
        if target_urls:
            self.api_urls = target_urls
            self.stats = {url: {"success": 0, "fail": 0, "total": 0} for url in target_urls}
        
        # 打印头部信息
        self.print_header()
        
        # 计算结束时间
        end_time = datetime.now() + timedelta(minutes=self.duration_minutes)
        total_request_count = 0
        total_success_count = 0
        total_fail_count = 0
        round_count = 0
        
        try:
            while datetime.now() < end_time:
                round_count += 1
                
                # 打印轮次分隔
                if round_count > 1:
                    self.write_log("")  # 空行分隔
                
                # 循环调用所有 API
                for api_url in urls_to_monitor:
                    # 检查是否超时
                    if datetime.now() >= end_time:
                        break
                    
                    total_request_count += 1
                    
                    # 调用 API
                    result = self.call_api(api_url, headers, self.ca_cert_path)
                    
                    # 更新统计
                    self.stats[api_url]['total'] += 1
                    if result["success"]:
                        total_success_count += 1
                        self.stats[api_url]['success'] += 1
                    else:
                        total_fail_count += 1
                        self.stats[api_url]['fail'] += 1
                    
                    # 记录单行日志
                    log_line = self.format_one_line_log(api_url, result, total_request_count)
                    self.write_log(log_line)
                    
                    # 等待下次请求（除了最后一个URL）
                    if api_url != urls_to_monitor[-1]:
                        remaining_time = (end_time - datetime.now()).total_seconds()
                        if remaining_time > 0:
                            time.sleep(min(self.interval_seconds, remaining_time))
                
                # 一轮结束后等待
                remaining_time = (end_time - datetime.now()).total_seconds()
                if remaining_time > 0:
                    time.sleep(min(self.interval_seconds, remaining_time))
                    
        except KeyboardInterrupt:
            self.write_log("\n\n监控被用户中断 (Ctrl+C)")
        
        # 输出统计信息
        self.print_summary(total_request_count, total_success_count, total_fail_count)
def main():
    # 方式1: 监控所有 API（默认）
    monitor = K8sAPIMonitor(duration_minutes=10, interval_seconds=0.1)
    monitor.run()
    
    # 方式2: 只监控指定的几个 API
    # monitor = K8sAPIMonitor(duration_minutes=5, interval_seconds=5)
    # monitor.run([
    #     "https://10.43.0.1:443/api/v1/namespaces/ai-gateway",
    #     "https://10.1.104.101:6443/api/v1/namespaces/ai-gateway",
    #     "https://10.1.104.102:6443/api/v1/namespaces/ai-gateway"
    # ])
    
    # 方式3: 快速测试（1分钟，每3秒）
    # monitor = K8sAPIMonitor(duration_minutes=1, interval_seconds=3)
    # monitor.run()
if __name__ == "__main__":
    main()